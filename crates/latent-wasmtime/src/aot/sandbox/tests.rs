use super::*;

#[test]
fn finite_limits_reject_zero_excess_and_inconsistent_budgets() {
    let valid = SandboxLimits::default();
    assert_eq!(valid.validate().unwrap(), valid);
    for limits in [
        SandboxLimits {
            address_space_bytes: 0,
            ..valid
        },
        SandboxLimits {
            address_space_bytes: 4 * 1024 * 1024 * 1024 + 1,
            ..valid
        },
        SandboxLimits {
            cpu_seconds: 0,
            ..valid
        },
        SandboxLimits {
            cpu_seconds: 301,
            ..valid
        },
        SandboxLimits {
            stack_bytes: 1024,
            ..valid
        },
        SandboxLimits {
            stack_bytes: 64 * 1024 * 1024 + 1,
            ..valid
        },
        SandboxLimits {
            maximum_fds: 7,
            ..valid
        },
        SandboxLimits {
            maximum_fds: 65,
            ..valid
        },
    ] {
        assert_eq!(
            limits.validate().unwrap_err().code,
            PlatformErrorCode::InvalidArgument
        );
    }
}

#[test]
fn configuration_is_closed_and_cannot_encode_enforcement() {
    let value = serde_json::to_value(SandboxLimits::default()).unwrap();
    assert_eq!(value.as_object().unwrap().len(), 4);
    assert_eq!(value["cpuSeconds"], 30);
    let mut forged = value;
    forged["enforced"] = true.into();
    assert!(serde_json::from_value::<SandboxLimits>(forged).is_err());
    assert_eq!(
        bootstrap(SandboxLimits::default(), 0).unwrap_err().code,
        PlatformErrorCode::InvalidArgument
    );
}

#[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
#[test]
fn unsupported_platform_never_yields_a_prepared_capability() {
    assert_eq!(
        bootstrap(SandboxLimits::default(), 1).unwrap_err().code,
        PlatformErrorCode::IncompatibleContract
    );
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod filter {
    use super::super::policy;

    const ALLOW: u32 = 0x7fff_0000;

    // Evaluate the actual library-generated classic BPF against synthetic
    // seccomp_data. This avoids irreversibly sandboxing the shared test runner.
    // Real kernel enforcement is exercised in the dedicated compiler child.
    fn action(syscall: i64, args: [u64; 6], architecture: u32) -> u32 {
        let program = policy::build().unwrap();
        let mut data = [0_u8; 64];
        data[..4].copy_from_slice(&i32::try_from(syscall).unwrap().to_le_bytes());
        data[4..8].copy_from_slice(&architecture.to_le_bytes());
        for (index, arg) in args.into_iter().enumerate() {
            data[16 + 8 * index..24 + 8 * index].copy_from_slice(&arg.to_le_bytes());
        }
        let mut accumulator = 0_u32;
        let mut pc = 0_usize;
        for _ in 0..1024 {
            let instruction = &program[pc];
            pc += 1;
            match instruction.code {
                0x20 => {
                    let offset = usize::try_from(instruction.k).unwrap();
                    accumulator = u32::from_le_bytes(data[offset..offset + 4].try_into().unwrap());
                }
                0x54 => accumulator &= instruction.k,
                0x05 => pc += usize::try_from(instruction.k).unwrap(),
                0x15 | 0x25 | 0x35 => {
                    let matched = match instruction.code {
                        0x15 => accumulator == instruction.k,
                        0x25 => accumulator > instruction.k,
                        _ => accumulator >= instruction.k,
                    };
                    pc += usize::from(if matched {
                        instruction.jt
                    } else {
                        instruction.jf
                    });
                }
                0x06 => return instruction.k,
                unknown => panic!("unhandled generated BPF opcode {unknown:#x}"),
            }
        }
        panic!("fixed sandbox policy did not terminate within its instruction bound")
    }

    fn permits(syscall: i64, args: [u64; 6]) -> bool {
        action(syscall, args, 0xc000_003e) == ALLOW
    }

    #[test]
    fn descriptor_operations_are_scoped_to_the_directional_pipes() {
        assert!(permits(libc::SYS_read, [0; 6]));
        assert!(!permits(libc::SYS_read, [1, 0, 0, 0, 0, 0]));
        assert!(!permits(libc::SYS_readv, [3, 0, 0, 0, 0, 0]));
        for fd in [1, 2] {
            assert!(permits(libc::SYS_write, [fd, 0, 0, 0, 0, 0]));
            assert!(permits(libc::SYS_writev, [fd, 0, 0, 0, 0, 0]));
        }
        assert!(!permits(libc::SYS_write, [0; 6]));
        assert!(!permits(libc::SYS_write, [3, 0, 0, 0, 0, 0]));
        assert!(!permits(libc::SYS_fstat, [3, 0, 0, 0, 0, 0]));
    }

    #[test]
    fn memory_requires_anonymous_private_nonexecutable_mappings() {
        let mapping = [0, 4096, 3, 0x22, u64::MAX, 0];
        assert!(permits(libc::SYS_mmap, mapping));
        let mut zero_extended_fd = mapping;
        zero_extended_fd[4] = u64::from(u32::MAX);
        assert!(permits(libc::SYS_mmap, zero_extended_fd));
        for (argument, value) in [
            (2, 4),
            (2, 5),
            (2, 7),
            (3, 0x32),
            (3, 0x02),
            (4, 0),
            (5, 4096),
        ] {
            let mut denied = mapping;
            denied[argument] = value;
            assert!(!permits(libc::SYS_mmap, denied));
        }
        assert!(permits(libc::SYS_mprotect, [0, 4096, 3, 0, 0, 0]));
        assert!(!permits(libc::SYS_mprotect, [0, 4096, 5, 0, 0, 0]));
        assert!(!permits(libc::SYS_pkey_mprotect, [0; 6]));
        assert!(!permits(libc::SYS_mremap, [0; 6]));
    }

    #[test]
    fn ambient_authority_and_alternative_abis_are_denied() {
        for syscall in [
            libc::SYS_open,
            libc::SYS_openat,
            libc::SYS_openat2,
            libc::SYS_socket,
            libc::SYS_socketpair,
            libc::SYS_connect,
            libc::SYS_sendmsg,
            libc::SYS_recvmsg,
            libc::SYS_clone,
            libc::SYS_clone3,
            libc::SYS_fork,
            libc::SYS_vfork,
            libc::SYS_execve,
            libc::SYS_execveat,
            libc::SYS_ptrace,
            libc::SYS_process_vm_readv,
            libc::SYS_process_vm_writev,
            libc::SYS_pidfd_getfd,
            libc::SYS_io_uring_setup,
            libc::SYS_personality,
            libc::SYS_prlimit64,
            libc::SYS_setrlimit,
            libc::SYS_prctl,
            libc::SYS_seccomp,
            libc::SYS_mount,
            libc::SYS_unshare,
            libc::SYS_setns,
            libc::SYS_memfd_create,
            libc::SYS_kill,
            libc::SYS_tgkill,
        ] {
            assert!(
                !permits(syscall, [0; 6]),
                "syscall {syscall} unexpectedly allowed"
            );
        }
        assert_ne!(action(libc::SYS_read, [0; 6], 0x4000_0003), ALLOW);
        assert!(!permits(libc::SYS_read | 0x4000_0000, [0; 6]));
    }

    #[test]
    fn random_and_synchronization_permissions_are_bounded() {
        assert!(permits(libc::SYS_getrandom, [0, 256, 1, 0, 0, 0]));
        assert!(!permits(libc::SYS_getrandom, [0, 257, 1, 0, 0, 0]));
        assert!(!permits(libc::SYS_getrandom, [0, 16, 2, 0, 0, 0]));
        assert!(permits(libc::SYS_futex, [0, 129, 0, 0, 0, 0]));
        assert!(!permits(libc::SYS_futex, [0, 1, 0, 0, 0, 0]));
    }
}
