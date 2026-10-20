use std::io::{Cursor, Read};

static TEXT: &str = include_str!("text.txt");
static BINARY: &[u8] = include_bytes!("binary.bin");
static EMPTY_TEXT: &str = include_str!("empty.txt");
static EMPTY_BYTES: &[u8] = include_bytes!("empty.bin");

pub fn read(mode: &str) -> String {
    match mode {
        "text" => {
            assert_eq!(TEXT, "Gr\u{fc}\u{df}e\0\u{96ea}\n");
            format!("resource|text={TEXT}")
        }
        "binary" => {
            assert_eq!(BINARY, &[0,255,128,65,13,10]);
            "resource|binary=00ff80410d0a".to_owned()
        }
        "empty" => {
            assert_eq!(EMPTY_TEXT, "");
            assert_eq!(EMPTY_BYTES, &[]);
            assert_eq!(Cursor::new(EMPTY_BYTES).read(&mut [0;1]).unwrap(), 0);
            "resource|empty=0+0|eof=1".to_owned()
        }
        "independent" => {
            let mut second = Cursor::new(BINARY);
            let mut a = [0;2]; let mut b = [0;2];
            {
                let mut first = Cursor::new(BINARY);
                first.read_exact(&mut a).unwrap(); second.read_exact(&mut b).unwrap();
                assert_eq!(a,b); assert_eq!(a,[0,255]);
            }
            second.read_exact(&mut b).unwrap(); assert_eq!(b,[128,65]);
            "resource|independent=2,2|drop=other-readable".to_owned()
        }
        "trap" => { assert_eq!(BINARY.len(),6); panic!("requested resource trap"); }
        _ => panic!("unknown fixed resource case"),
    }
}
