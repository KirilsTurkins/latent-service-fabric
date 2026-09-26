//! Finite owned TLS protocol faults, without an external server dependency.
use super::*;
use std::sync::atomic::AtomicUsize;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt, BufReader},
    net::TcpListener,
    sync::{oneshot, Notify},
};
#[derive(Clone, Copy)]
pub enum Mode {
    WrongStream,
    Malformed,
    Oversized,
    NoResponders,
    Slow,
    Hold,
    Flood,
    Healthy,
}
pub struct Stub {
    pub config: NatsConfig,
    pub observed: Arc<Notify>,
    pub publishes: Arc<AtomicUsize>,
    stop: Option<oneshot::Sender<()>>,
    task: tokio::task::JoinHandle<()>,
}
impl Stub {
    pub async fn new(mode: Mode) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let (acceptor, root) = proxy::identity();
        let config = config_for(listener.local_addr().unwrap().port(), root);
        let observed = Arc::new(Notify::new());
        let publishes = Arc::new(AtomicUsize::new(0));
        let (signal, count) = (observed.clone(), publishes.clone());
        let (stop, mut stopped) = oneshot::channel();
        let task = tokio::spawn(async move {
            let mut children = tokio::task::JoinSet::new();
            let mut accepted = 0;
            loop {
                tokio::select! {
                    _=&mut stopped=>break,
                    result=children.join_next(),if !children.is_empty()=>{result.unwrap().unwrap();},
                    stream=listener.accept(),if accepted<16=>{
                        let stream=stream.unwrap().0;accepted+=1;
                        let (acceptor,signal,count)=(acceptor.clone(),signal.clone(),count.clone());
                        children.spawn(async move {
                            let _=tokio::time::timeout(Duration::from_secs(3),async {
                                let mut stream=BufReader::with_capacity(8192,acceptor.accept(stream).await?);
                                stream.get_mut().write_all(b"INFO {\"headers\":true,\"tls_required\":true,\"max_payload\":65536}\r\n").await?;
                                for _ in 0..64 {
                                    let line=proxy::line(&mut stream).await?;
                                    if line==b"PING\r\n" {
                                        if matches!(mode,Mode::Slow) {tokio::time::sleep(Duration::from_millis(30)).await;}
                                        let response=if matches!(mode,Mode::Flood) {b"PING\r\nPING\r\nPING\r\nPING\r\nPING\r\nPING\r\nPING\r\nPING\r\nPING\r\n".as_slice()}else{b"PONG\r\n"};
                                        stream.get_mut().write_all(response).await?;
                                    } else if line.starts_with(b"HPUB ") {
                                        let words:Vec<_>=std::str::from_utf8(&line).unwrap().trim_end().split(' ').collect();assert_eq!(words.len(),5);
                                        let size:usize=words[4].parse().unwrap();assert!(size<=65536);
                                        let mut body=vec![0;size+2];stream.read_exact(&mut body).await?;
                                        count.fetch_add(1,Ordering::AcqRel);
                                        if matches!(mode,Mode::Hold) {signal.notify_one();let _=stream.read_u8().await;return Ok::<(),std::io::Error>(());}
                                        let inbox=words[2];
                                        let response=match mode {Mode::WrongStream=>br#"{"stream":"FOREIGN","seq":1}"#.as_slice(),Mode::Malformed=>b"{private-server-diagnostic",_=>br#"{"stream":"ORDERS","seq":1}"#};
                                        let frame=if matches!(mode,Mode::Oversized) {format!("MSG {inbox} 1 99999\r\n").into_bytes()}
                                        else if matches!(mode,Mode::NoResponders) {let body=b"NATS/1.0 503\r\n\r\n";[format!("HMSG {inbox} 1 {} {}\r\n",body.len(),body.len()).into_bytes(),body.to_vec(),b"\r\n".to_vec()].concat()}
                                        else {[format!("MSG {inbox} 1 {}\r\n",response.len()).into_bytes(),response.to_vec(),b"\r\n".to_vec()].concat()};
                                        stream.get_mut().write_all(&frame).await?;
                                    }
                                }
                                Ok::<(),std::io::Error>(())
                            }).await;
                        });
                    }
                }
            }
            children.abort_all();
            while let Some(result) = children.join_next().await {
                assert!(result.is_ok() || result.unwrap_err().is_cancelled());
            }
        });
        Self {
            config,
            observed,
            publishes,
            stop: Some(stop),
            task,
        }
    }
    pub async fn close(mut self) {
        let _ = self.stop.take().unwrap().send(());
        tokio::time::timeout(Duration::from_secs(1), &mut self.task)
            .await
            .unwrap()
            .unwrap();
    }
}
impl Drop for Stub {
    fn drop(&mut self) {
        if let Some(stop) = self.stop.take() {
            let _ = stop.send(());
        }
        self.task.abort();
    }
}
