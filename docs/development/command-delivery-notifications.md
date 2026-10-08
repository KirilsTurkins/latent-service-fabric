# Bounded command delivery notifications

`latent-node::command_waiters` supplies finite duplicate-delivery notifications
for the existing [atomic command envelope](atomic-command-envelope.md). It does
not store results, open the database, run a guest, create a worker or own command
cancellation. The original `latent-commit::atomic` claim and complete envelope
remain the sole admission and durable disposition owners.

## Admission and authorization ports

The node prepares one `CommandWaiterRegistry` with fixed owner/waiter capacities
and a finite resident-byte ceiling. Construction checks all count/byte arithmetic
before allocating its tables. Registration and attachment never grow them.
The node accounts the reported fixed resident reservation until the last registry
or delivery handle retires, even if every occupied slot has been released.

`register(&AdmittedCommand)` accepts only the atomic writer's affine, already
published claim. The returned notification owner moves into the existing command
driver before guest scheduling. A copied/decoded record cannot register an owner;
double registration of the same command, attempt and physical transaction
identity fails. There is no alternate command claim or request fingerprint.

`attach(&CommandRecord, authorize)` consumes the original record from a fresh
authorized `atomic::inspect`/admission observation. The host callback repeats the
current application/coalescing and result-read policy checks before any table
observation or slot admission. It must use the authenticated stable caller or
explicitly granted recovery scope and the record's captured result-read policy.
Credentials, authorization decisions, business input, selected source, transport
deadline and cancellation tokens are not retained in the notification table.

A terminal record returns `ReloadDurableState`. A pending record with no tracked
notification source returns `RecoveryRequired`. This includes the short durable
publish/register gap and an interrupted driver; neither response proves abort,
never-started work or permission to run another guest. The manager must retain
its actual affine command owner when registration fails. It may publish a
technical abort only through the existing private physical-retirement proof.
Notification capacity never evicts a durable identity or retained result.

## Delivery and physical ownership

An attached waiter uses the original bounded RPC/HTTP delivery deadline and its
existing transport byte reservation. It creates no background timer or poller.
Dropping a duplicate waiter detaches only that delivery slot. It cannot shorten
the legitimate driver's deadline, alter its input, cancel it or retire physical
executor/I/O/cleanup guards.

Finishing or dropping the affine notification owner wakes attached waiters with
the same `ReloadDurableState` hint. Every caller reloads through the authoritative
atomic inspection and current result-read authorization before exposing a
result. A wake is not a committed receipt, technical-abort proof or durable
rejection. A missed/dropped transport response is recovered under the original
command identity, without executing the mutation body again.

Finished waiter slots remain reserved until the actual waiter completes or is
dropped. Full table pressure refuses another waiter. Generational slot tokens
and the original attempt/transaction identity prevent a previous retry or late
delivery handle from removing or waking a newer attempt. Full-width generation
exhaustion fails closed. Waker callbacks run outside table locks; a panicking
callback cannot unwind the command driver's destructor or suppress other hints.

Explicit command cancellation still belongs to the existing authenticated
activation manager and atomic commit fence. This module has no cancellation
operation. Unknown/expired history, an absent notifier or waiter cancellation
cannot produce a new retry request or replace the server-issued abort fence.

## Validation and remaining integration

The focused node tests use the actual embedded engine and complete envelopes:
simultaneous claim CAS and duplicate delivery races, one immutable effect set,
lost committed response and database reopen, compatible source rollout, retained
business rejection, result expiry, dropped physical-work/waiter distinction,
current caller/read callbacks, stable subject token rotation, explicit shared
scope denial, private proven-abort retry generations, fixed-capacity pressure,
slot reuse, generation exhaustion and reentrant/panicking executor callbacks.

The 17 new cases passed with Rust 1.97.1 on Linux; the complete 94-case node
library passed on Windows. The suite catalogue preserves the original 77 case
names and registers all 17 discovered native cases. Standard node Clippy,
formatting, documentation and CI command ownership checks passed. An exploratory
strict node Clippy run retained its existing out-of-scope warnings; this source
milestone adds no warning in the new notification modules.

These tests establish the bounded notification ports and actual atomic record
behavior. They do not establish an implemented `TransactionService`, standalone
command admission/scheduling, physical commit/cancellation arbitration or any
guest-language compatibility. Manager/wire integration must connect these ports
to the existing protected storage workers and real authenticated authority;
durable result lookup cannot be replaced by cached notification data. The shared
transaction runtime and all six real guest qualifications remain separate
acceptance work for #387/#388/#389/#718. The Phase 4 issues remain open.
