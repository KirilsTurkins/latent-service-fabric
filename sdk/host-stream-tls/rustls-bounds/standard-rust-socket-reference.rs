#[no_mangle]
pub extern "C" fn connect_status() -> u32 {
    let address = std::net::SocketAddr::from(([127, 0, 0, 1], 9));
    match std::net::TcpStream::connect(address) {
        Ok(_) => 0,
        Err(error) if error.kind() == std::io::ErrorKind::Unsupported => 1,
        Err(_) => 2,
    }
}
