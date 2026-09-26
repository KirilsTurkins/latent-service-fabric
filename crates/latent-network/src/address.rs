use crate::NetworkError;
use ipnet::IpNet;
use serde::{Deserialize, Serialize};
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AddressPolicy {
    pub networks: Vec<IpNet>,
    pub special_addresses: Vec<IpAddr>,
}

impl AddressPolicy {
    pub fn validate(&self) -> Result<(), NetworkError> {
        if self.networks.is_empty()
            || self.networks.len() > 16
            || self.special_addresses.len() > 16
            || self.special_addresses.iter().any(|address| {
                let address = canonical(*address);
                address.is_unspecified()
                    || address.is_multicast()
                    || !self
                        .networks
                        .iter()
                        .any(|network| network.contains(&address))
            })
        {
            return Err(NetworkError::InvalidConfiguration);
        }
        Ok(())
    }

    #[must_use]
    pub fn permits(&self, address: IpAddr) -> bool {
        let address = canonical(address);
        self.networks
            .iter()
            .any(|network| network.contains(&address))
            && (!special(address)
                || self
                    .special_addresses
                    .iter()
                    .any(|allowed| canonical(*allowed) == address))
    }
}

#[must_use]
pub fn canonical(address: IpAddr) -> IpAddr {
    match address {
        IpAddr::V6(address) => address
            .to_ipv4_mapped()
            .map_or(IpAddr::V6(address), IpAddr::V4),
        address @ IpAddr::V4(_) => address,
    }
}

fn special(address: IpAddr) -> bool {
    match address {
        IpAddr::V4(address) => special4(address),
        IpAddr::V6(address) => special6(address),
    }
}

fn special4(address: Ipv4Addr) -> bool {
    let [first, second, third, _] = address.octets();
    address == Ipv4Addr::new(168, 63, 129, 16)
        || first == 0
        || first == 10
        || first == 127
        || first >= 224
        || (first == 100 && (64..=127).contains(&second))
        || (first == 169 && second == 254)
        || (first == 172 && (16..=31).contains(&second))
        || (first == 192
            && ((second == 0 && (third == 0 || third == 2))
                || (second == 88 && third == 99)
                || second == 168))
        || (first == 198 && ((second == 18 || second == 19) || (second == 51 && third == 100)))
        || (first == 203 && second == 0 && third == 113)
}

fn special6(address: Ipv6Addr) -> bool {
    let [first, second, _, _, _, _, _, _] = address.segments();
    first & 0xe000 != 0x2000
        || first == 0x2002
        || (first == 0x2001 && (second < 0x200 || second == 0xdb8))
        || first == 0x3fff
}
