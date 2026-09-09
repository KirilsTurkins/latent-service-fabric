use super::{
    call::{self, Offer},
    observation,
    publication::Target,
    Clock, Node, Result, Writer,
};
use latent_core::{ActivationId, DeadlineDiagnosticObserver};
use latent_telemetry::TelemetryRecord;
use latent_wire::invocation::{proto, InvocationServiceClient};
use serde_json::{json, Value};
use std::time::Duration;

pub(super) struct State {
    pub targets: Vec<Target>,
    pub offered: u64,
    pub passed: bool,
    pub functional_logs: usize,
    pub jobs: Vec<Option<tokio::task::JoinHandle<Result<Value>>>>,
    pub revisions: Vec<Option<String>>,
}
impl State {
    pub fn new(targets: Vec<Target>) -> Self {
        Self {
            targets,
            offered: 0,
            passed: true,
            functional_logs: 0,
            jobs: Vec::with_capacity(5),
            revisions: vec![None; 8],
        }
    }
    pub fn start(&mut self, node: &mut Node, clock: Clock, mut offer: Offer) -> Result<usize> {
        if self.jobs.iter().filter(|v| v.is_some()).count() >= 5 {
            return Err("engine owned task bound".into());
        }
        node.command(true)?;
        self.offered += 1;
        offer.ordinal = self.offered;
        offer.command_ordinal = node.work.commands;
        let index = self
            .jobs
            .iter()
            .position(Option::is_none)
            .unwrap_or(self.jobs.len());
        let job = Some(tokio::spawn(call::invoke(node.channel(), clock, offer)));
        if index == self.jobs.len() {
            self.jobs.push(job);
        } else {
            self.jobs[index] = job;
        }
        Ok(index)
    }
    pub fn pending(&self, index: usize) -> bool {
        self.jobs
            .get(index)
            .and_then(Option::as_ref)
            .is_some_and(|v| !v.is_finished())
    }
    pub async fn finish(
        &mut self,
        index: usize,
        node: &mut Node,
        clock: Clock,
        offer: &Offer,
        observer: &DeadlineDiagnosticObserver,
        writer: &mut Writer,
    ) -> Result<()> {
        let result = self
            .jobs
            .get_mut(index)
            .and_then(Option::as_mut)
            .ok_or("engine missing job")?
            .await;
        self.jobs[index].take();
        let mut row = result??;
        row["timing"] = node
            .owner
            .backend
            .take_invocation_timing(&ActivationId(offer.id.clone()))
            .map_or(Value::Null, super::super::evidence::timing);
        row["guest_logs"] = json!(super::oracle::logs(node, &offer.id)?);
        row["native_after_response"] = observation::native(node);
        row["diagnostic_token"] = json!(observer
            .token_for_activation(&offer.id)
            .map(|v| v.id().to_string()));
        let semantic = super::oracle::check(offer, &row, observer);
        row["semantic_validated"] = json!(semantic);
        self.passed &= semantic;
        if offer.phase == "functional" {
            self.functional_logs += row["guest_logs"].as_array().map_or(0, Vec::len);
            row["cleanup_log"] = cleanup(node, &offer.id).await?;
            self.passed &= row["cleanup_log"]["attributes"]["cleanup"] == "released";
        }
        if let Some(revision) = row["response"]["revision_id"]
            .as_str()
            .filter(|v| !v.is_empty())
        {
            let target = self
                .targets
                .iter()
                .position(|v| v.tenant == offer.target.tenant && v.service == offer.target.service)
                .ok_or("engine target pin")?;
            if let Some(previous) = &self.revisions[target] {
                self.passed &= previous == revision;
            } else {
                self.revisions[target] = Some(revision.into());
            }
        }
        let consumption = row["response"]["consumption"].clone();
        writer.sample(&row)?;
        self.status(node, clock, offer, &consumption, writer).await
    }
    async fn status(
        &mut self,
        node: &mut Node,
        clock: Clock,
        offer: &Offer,
        consumption: &Value,
        writer: &mut Writer,
    ) -> Result<()> {
        node.command(false)?;
        let started = clock.elapsed();
        let response = super::super::cold::call::status(
            InvocationServiceClient::new(node.channel())
                .get_activation(call::auth(
                    proto::GetActivationRequest {
                        activation_id: offer.id.clone(),
                    },
                    &offer.target.tenant,
                    Duration::from_secs(1),
                )?)
                .await,
        );
        let expected = offer
            .expected_code
            .map_or_else(|| "completed".to_owned(), |s| s.replace('-', "_"));
        self.passed &= response["grpc_code"] == 0
            && response["activation_id"] == offer.id
            && response["terminal_state"] == expected
            && &response["consumption"] == consumption;
        writer.sample(&json!({"kind":"command","ordinal":node.work.commands.to_string(),"operation":"get-activation","target":offer.id,"tenant":offer.target.tenant,"started_nanos":started.to_string(),"finished_nanos":clock.elapsed().to_string(),"response":response}))
    }
    pub async fn cancel(
        &mut self,
        node: &mut Node,
        clock: Clock,
        offer: &Offer,
        writer: &mut Writer,
    ) -> Result<()> {
        node.command(false)?;
        let started = clock.elapsed();
        let response = match InvocationServiceClient::new(node.channel())
            .cancel(call::auth(
                proto::CancelRequest {
                    activation_id: offer.id.clone(),
                    reason: "engine fixed functional cancellation".into(),
                },
                &offer.target.tenant,
                Duration::from_secs(1),
            )?)
            .await
        {
            Ok(response) => {
                let r = response.into_inner();
                json!({"grpc_code":0,"disposition":r.disposition,"terminal_state":r.terminal_state})
            }
            Err(error) => json!({"grpc_code":error.code() as i32}),
        };
        self.passed &= response["grpc_code"] == 0 && response["disposition"] == 1;
        writer.sample(&json!({"kind":"command","ordinal":node.work.commands.to_string(),"operation":"cancel","target":offer.id,"tenant":offer.target.tenant,"started_nanos":started.to_string(),"finished_nanos":clock.elapsed().to_string(),"response":response}))
    }
    pub async fn abort_and_join(&mut self) -> Result<()> {
        for job in self.jobs.iter().flatten() {
            job.abort();
        }
        for slot in &mut self.jobs {
            if let Some(job) = slot.as_mut() {
                let _ = job.await;
            }
            slot.take();
        }
        Ok(())
    }
}
impl Drop for State {
    fn drop(&mut self) {
        for job in self.jobs.iter().flatten() {
            job.abort();
        }
    }
}

async fn cleanup(node: &Node, id: &str) -> Result<Value> {
    tokio::time::timeout(Duration::from_secs(1), node.owner.telemetry.flush())
        .await
        .map_err(|_| "engine telemetry flush")?
        .map_err(super::super::super::platform)?;
    let mut found = None;
    for value in node.owner.sink.records() {
        if let TelemetryRecord::Log(log) = value {
            if log.attributes.get("activation_id").map(String::as_str) == Some(id)
                && log.attributes.get("stage").map(String::as_str) == Some("cleanup")
            {
                if found.is_some() {
                    return Err("engine duplicate cleanup log".into());
                }
                found = Some(
                    json!({"body":log.body,"attributes":log.attributes,"observed_at_unix_millis":log.observed_at_unix_millis.to_string()}),
                );
            }
        }
    }
    Ok(found.unwrap_or(Value::Null))
}

pub(super) fn ordinary(
    target: &Target,
    phase: &str,
    index: u32,
    warmup: u32,
    clock: Clock,
) -> Result<Offer> {
    let (function, payload, expected) = match phase {
        "echo" | "concurrent-echo" => (
            "echo",
            json!([super::super::INPUT]),
            json!([{"ok":super::super::INPUT}]),
        ),
        "compute" => {
            let input = json!([7, 65_536]);
            let output =
                latent_optimization_workloads::invoke("compute", &serde_json::to_vec(&input)?)
                    .map_err(std::io::Error::other)?;
            ("compute", input, serde_json::from_slice(&output)?)
        }
        "memory" => ("run", json!(["success"]), json!([692_060_160])),
        _ => return Err("engine ordinary phase".into()),
    };
    Ok(Offer {
        ordinal: 0,
        command_ordinal: 0,
        phase: phase.into(),
        phase_kind: if index < warmup { "warmup" } else { "measured" }.into(),
        index,
        id: format!("engine-{phase}-{index:04}"),
        target: target.clone(),
        function: function.into(),
        payload,
        expected: Some(expected),
        grant: call::grant("G"),
        expected_code: None,
        scheduled: clock.elapsed(),
    })
}
