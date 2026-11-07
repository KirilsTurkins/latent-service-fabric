from pathlib import Path
p = Path('tools/toolchain-smoke/examples/rust_http_pump_control.rs')
s = p.read_text().replace('Arc<[Arc<Gate>; 3]>', 'Arc<[Arc<Gate>; 4]>')
s = s.replace('let mut second_returned = false;', '''let mut second_returned = false;
            let mut third = Box::pin(run.call_concurrent(access, (2,)));
            let mut third_returned = false;''')
a = s.index('                if second_returned {')
b = s.index('                assert!(', a)
s = s[:a] + '''                if third_returned {
                    return first_poll.map(|result| {
                        assert_eq!(result?, (0,));
                        Ok(())
                    });
                }
                if second_returned {
                    assert!(first_poll.is_pending(), "original lost its hold before third completion");
                    match third.as_mut().poll(cx) {
                        Poll::Ready(value) => {
                            assert_eq!(value?, (2,));
                            assert!(!gates[0].ready.load(Ordering::SeqCst));
                            assert_eq!(gates[0].live.load(Ordering::SeqCst), 1);
                            assert_eq!(gates[2].live.load(Ordering::SeqCst), 0);
                            third_returned = true;
                            gates[0].release();
                        }
                        Poll::Pending => {
                            if gates[2].polls.load(Ordering::SeqCst) != 0 {
                                gates[2].release();
                            }
                        }
                    }
                    return Poll::Pending;
                }
''' + s[b:]
s = s.replace('second_returned = true;\n                        gates[0].release();', 'second_returned = true;\n                        cx.waker().wake_by_ref();')
s = s.replace('&gates[..2]', '&gates[..3]')
a = s.index('    tokio::time::timeout(Duration::from_secs(5), retire.')
s = s[:a] + s[a:].replace('(2,)', '(3,)').replace('gates[2]', 'gates[3]')
s = s.replace('sibling before held release;', 'two sequential siblings before held release;')
p.write_text(s)
