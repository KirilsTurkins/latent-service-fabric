use super::{config, proto, receipt};
use crate::client::Session;
use crate::management::triggers::{execute, TriggerOperation};
use std::collections::VecDeque;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tonic::{Request, Response, Status};

#[derive(Clone)]
struct LookupReplies(Arc<Mutex<VecDeque<proto::GetTriggerOperationResponse>>>);

#[tonic::async_trait]
impl proto::trigger_service_server::TriggerService for LookupReplies {
    async fn apply_trigger(
        &self,
        _: Request<proto::ApplyTriggerRequest>,
    ) -> Result<Response<proto::ApplyTriggerResponse>, Status> {
        panic!("read-only recovery must not send a mutation");
    }
    async fn get_trigger(
        &self,
        _: Request<proto::GetTriggerRequest>,
    ) -> Result<Response<proto::GetTriggerResponse>, Status> {
        panic!("original operation lookup must not change its selector");
    }
    async fn list_triggers(
        &self,
        _: Request<proto::ListTriggersRequest>,
    ) -> Result<Response<proto::ListTriggersResponse>, Status> {
        panic!("original operation lookup must not scan triggers");
    }
    async fn delete_trigger(
        &self,
        _: Request<proto::DeleteTriggerRequest>,
    ) -> Result<Response<proto::Empty>, Status> {
        panic!("read-only recovery must not delete a trigger");
    }
    async fn get_trigger_operation(
        &self,
        request: Request<proto::GetTriggerOperationRequest>,
    ) -> Result<Response<proto::GetTriggerOperationResponse>, Status> {
        assert_eq!(request.into_inner().operation_id, "create");
        Ok(Response::new(
            self.0
                .lock()
                .unwrap()
                .pop_front()
                .expect("one reply per original lookup"),
        ))
    }
}

struct ServerTask(tokio::task::JoinHandle<Result<(), tonic::transport::Error>>);
impl Drop for ServerTask {
    fn drop(&mut self) {
        self.0.abort();
    }
}

#[tokio::test]
async fn empty_and_pruned_original_operation_journals_remain_unknown_without_execution_permission()
{
    let unknown = proto::TriggerOperationLookupDisposition::Unknown as i32;
    let replies = [
        (1, 0, None, unknown, true),
        (1, 1, None, unknown, true),
        (9, 8, None, unknown, true),
        (u64::MAX, u64::MAX, None, unknown, true),
        (2, 0, None, unknown, false),
        (10, 8, None, unknown, false),
        (1, 0, Some(receipt()), unknown, false),
        (
            0,
            0,
            None,
            proto::TriggerOperationLookupDisposition::Found as i32,
            false,
        ),
    ];
    let queue = Arc::new(Mutex::new(
        replies
            .iter()
            .map(
                |(floor, high, receipt, disposition, _)| proto::GetTriggerOperationResponse {
                    retained_floor: *floor,
                    high_watermark: *high,
                    receipt: receipt.clone(),
                    disposition: *disposition,
                },
            )
            .collect::<VecDeque<_>>(),
    ));
    let incoming =
        tonic::transport::server::TcpIncoming::bind("127.0.0.1:0".parse().unwrap()).unwrap();
    let address = incoming.local_addr().unwrap();
    let (stop, stopped) = tokio::sync::oneshot::channel();
    let mut server = ServerTask(tokio::spawn(
        tonic::transport::Server::builder()
            .add_service(proto::trigger_service_server::TriggerServiceServer::new(
                LookupReplies(Arc::clone(&queue)),
            ))
            .serve_with_incoming_shutdown(incoming, async {
                let _ = stopped.await;
            }),
    ));
    let mut configured = config();
    configured.endpoint = format!("http://{address}");
    tokio::time::timeout(Duration::from_secs(5), async {
        for (floor, high, _, _, accepted) in replies {
            let session = Session::connect(&configured, None).await.unwrap();
            let result = execute::execute(
                TriggerOperation::Lookup(proto::GetTriggerOperationRequest {
                    operation_id: "create".into(),
                }),
                &session,
            )
            .await;
            if accepted {
                let result = result.unwrap();
                assert!(!result.outcome_known);
                assert_eq!(result.data["disposition"], "unknown");
                assert!(result.data["receipt"].is_null());
                assert_eq!(result.data["retainedFloor"], floor.to_string());
                assert_eq!(result.data["highWatermark"], high.to_string());
                assert_eq!(result.data["executionPermission"], false);
            } else {
                assert!(result.is_err());
            }
        }
        assert!(queue.lock().unwrap().is_empty());
        let _ = stop.send(());
        (&mut server.0).await.unwrap().unwrap();
    })
    .await
    .unwrap();
}
