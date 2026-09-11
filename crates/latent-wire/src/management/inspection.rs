use tonic::{Request, Response, Status};

use super::{
    errors, identifier, inventory, proto, ManagementOperation, ManagementServiceAdapter,
    RequestBudget,
};

#[tonic::async_trait]
impl proto::node_service_server::NodeService for ManagementServiceAdapter {
    async fn get_node(
        &self,
        mut request: Request<proto::GetNodeRequest>,
    ) -> Result<Response<proto::GetNodeResponse>, Status> {
        self.authenticate(&mut request, ManagementOperation::NodeInventory)?;
        let mut budget = RequestBudget::new::<proto::GetNodeRequest>(&self.limits)?;
        budget.string(&request.get_ref().node_id, self.limits.max_id_bytes)?;
        identifier(&request.get_ref().node_id, self.limits.max_id_bytes)?;
        self.check_encoded(request.get_ref())?;
        let value = self
            .services
            .inventory
            .snapshot()
            .await
            .map_err(|error| errors::platform_status(error, &self.limits))?;
        inventory::validate_inventory(&value, &self.limits)?;
        let value = if value.node.id.0 == request.get_ref().node_id {
            Some(
                inventory::node_inventory_to_proto(value)
                    .map_err(|_| Status::internal("invalid node inventory"))?,
            )
        } else {
            None
        };
        self.response(proto::GetNodeResponse { inventory: value })
    }

    async fn list_nodes(
        &self,
        mut request: Request<proto::ListNodesRequest>,
    ) -> Result<Response<proto::ListNodesResponse>, Status> {
        self.authenticate(&mut request, ManagementOperation::NodeInventory)?;
        let mut budget = RequestBudget::new::<proto::ListNodesRequest>(&self.limits)?;
        let query = request.get_ref();
        for filter in [&query.trust_class, &query.region, &query.zone]
            .into_iter()
            .flatten()
        {
            budget.string(filter, self.limits.max_string_bytes)?;
            identifier(filter, self.limits.max_string_bytes)?;
        }
        budget.page(query.page.as_ref(), &self.limits)?;
        if query
            .page
            .as_ref()
            .and_then(|page| page.page_token.as_ref())
            .is_some()
        {
            return Err(Status::invalid_argument(
                "a standalone node has no node-list continuation",
            ));
        }
        self.check_encoded(query)?;
        let value = self
            .services
            .inventory
            .snapshot()
            .await
            .map_err(|error| errors::platform_status(error, &self.limits))?;
        inventory::validate_inventory(&value, &self.limits)?;
        let matches = query
            .trust_class
            .as_ref()
            .is_none_or(|filter| value.node.trust_classes.contains(filter))
            && query
                .region
                .as_ref()
                .is_none_or(|filter| value.node.region.as_ref() == Some(filter))
            && query
                .zone
                .as_ref()
                .is_none_or(|filter| value.node.zone.as_ref() == Some(filter));
        let nodes = if matches {
            vec![inventory::node_inventory_to_proto(value)
                .map_err(|_| Status::internal("invalid node inventory"))?]
        } else {
            Vec::new()
        };
        self.response(proto::ListNodesResponse {
            nodes,
            page: Some(proto::PageResponse {
                next_page_token: None,
            }),
        })
    }

    async fn register_node(
        &self,
        _request: Request<proto::RegisterNodeRequest>,
    ) -> Result<Response<proto::RegisterNodeResponse>, Status> {
        Err(Status::unimplemented(
            "node registration is not supported by a standalone node",
        ))
    }
    async fn report_inventory(
        &self,
        _request: Request<proto::ReportInventoryRequest>,
    ) -> Result<Response<proto::Empty>, Status> {
        Err(Status::unimplemented(
            "inventory reporting is not supported by a standalone node",
        ))
    }
    async fn heartbeat(
        &self,
        _request: Request<proto::HeartbeatRequest>,
    ) -> Result<Response<proto::Empty>, Status> {
        Err(Status::unimplemented(
            "node heartbeats are not supported by a standalone node",
        ))
    }
}
