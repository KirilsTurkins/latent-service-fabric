use super::*;

pub(super) struct Random(u64);

impl Random {
    pub(super) fn new() -> Self {
        Self(0x1050_c0de_5eed_2026)
    }

    fn next(&mut self) -> u64 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        self.0
    }

    fn below(&mut self, ceiling: u32) -> u32 {
        u32::try_from(self.next() % u64::from(ceiling)).unwrap()
    }
}

pub(super) fn case(random: &mut Random, family: usize) -> (Vec<Type>, String) {
    match family {
        0 => scalars(random),
        1 => (
            vec![types()["record"].clone()],
            format!("[{}]", record(random)),
        ),
        2 => tags(random),
        3 => wide_list(random),
        _ => unreachable!(),
    }
}

fn text(random: &mut Random) -> String {
    let alphabet = [
        "",
        "plain",
        "quote\"slash\\",
        "\n\t\0",
        "\u{1f980}",
        "caf\u{e9}",
    ];
    let index = usize::try_from(random.below(u32::try_from(alphabet.len()).unwrap())).unwrap();
    serde_json::to_string(&format!("{}-{}", alphabet[index], random.below(1000))).unwrap()
}

fn scalars(random: &mut Random) -> (Vec<Type>, String) {
    let signature = vec![
        Type::Bool,
        Type::U8,
        Type::S32,
        Type::U64,
        Type::S64,
        Type::Float32,
        Type::Float64,
        Type::Char,
        Type::String,
    ];
    let signed = i64::from_ne_bytes(random.next().to_ne_bytes());
    let input = format!(
        r#"[{},{},{},"{}","{}","{}.25e-2","-0","\ud83e\udd80",{}]"#,
        random.below(2) == 0,
        random.below(256),
        i64::from(random.below(65536)) - 32768,
        random.next(),
        signed,
        random.below(1000),
        text(random),
    );
    (signature, input)
}

fn record(random: &mut Random) -> String {
    let name = text(random);
    let count = random.below(65536);
    match random.below(3) {
        0 => format!(r#"{{"name":{name},"count":{count}}}"#),
        1 => format!(r#"{{"count":{count},"name":{name}}}"#),
        _ => format!(r#"{{"count":{count},"\u006eame":{name}}}"#),
    }
}

fn variant(random: &mut Random) -> String {
    match random.below(3) {
        0 => r#"{"case":"empty"}"#.to_owned(),
        1 => format!(r#"{{"case":"number","value":"{}"}}"#, random.next()),
        _ => format!(
            r#"{{"value":"{}","\u0063ase":"nu\u006dber"}}"#,
            random.next()
        ),
    }
}

fn tags(random: &mut Random) -> (Vec<Type>, String) {
    let signature = ["variant", "nested", "result", "flags"]
        .map(|name| types()[name].clone())
        .to_vec();
    let variant = variant(random);
    let option = match random.below(3) {
        0 => r#"{"none":null}"#.to_owned(),
        1 => r#"{"some":{"none":null}}"#.to_owned(),
        _ => format!(r#"{{"some":{{"some":{}}}}}"#, text(random)),
    };
    let result = if random.below(2) == 0 {
        format!(r#"{{"ok":{}}}"#, text(random))
    } else {
        format!(r#"{{"err":{variant}}}"#)
    };
    let flags = match random.below(4) {
        0 => "[]",
        1 => r#"["admin","read","write"]"#,
        2 => r#"["write","read"]"#,
        _ => r#"["\u0072ead"]"#,
    };
    (signature, format!("[{variant},{option},{result},{flags}]"))
}

fn wide_list(random: &mut Random) -> (Vec<Type>, String) {
    let mut records = Vec::new();
    for _ in 0..random.below(4) {
        records.push(format!(
            r#"{{"c":{},"a":{},"b":{}}}"#,
            record(random),
            record(random),
            record(random),
        ));
    }
    (
        vec![types()["wide-list"].clone()],
        format!("[[{}]]", records.join(",")),
    )
}
