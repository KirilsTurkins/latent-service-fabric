//! Accounted dynamic lifting. Derived from the pinned 48.0.7 values.rs paths.
use super::*;
use crate::component::dynamic_memory::{self, DynamicValueMemory};
use alloc::sync::Arc;
trait AccountedCollect<T>: Iterator<Item = Result<T>> + ExactSizeIterator + Sized {
    fn collect_accounted(self, memory: Option<&Arc<dyn DynamicValueMemory>>) -> Result<Vec<T>> {
        let mut output = dynamic_memory::vector(memory, self.len())?;
        for value in self {
            output.push(value?);
        }
        Ok(output)
    }
}
impl<T, I: Iterator<Item = Result<T>> + ExactSizeIterator> AccountedCollect<T> for I {}
fn supported(ty: InterfaceType) -> Result<()> {
    match ty {
        InterfaceType::Own(_)
        | InterfaceType::Borrow(_)
        | InterfaceType::Map(_)
        | InterfaceType::Future(_)
        | InterfaceType::Stream(_)
        | InterfaceType::ErrorContext(_)
        | InterfaceType::FixedLengthList(_) => bail!("unsupported-accounted-dynamic-value"),
        _ => Ok(()),
    }
}
fn lift_inner(
    cx: &mut LiftContext<'_>,
    ty: InterfaceType,
    src: &mut Iter<'_, ValRaw>,
) -> Result<Val> {
    supported(ty)?;
    let memory = cx.dynamic_memory.clone();
    Ok(match ty {
        InterfaceType::Bool => Val::Bool(bool::linear_lift_from_flat(cx, ty, next(src))?),
        InterfaceType::S8 => Val::S8(i8::linear_lift_from_flat(cx, ty, next(src))?),
        InterfaceType::U8 => Val::U8(u8::linear_lift_from_flat(cx, ty, next(src))?),
        InterfaceType::S16 => Val::S16(i16::linear_lift_from_flat(cx, ty, next(src))?),
        InterfaceType::U16 => Val::U16(u16::linear_lift_from_flat(cx, ty, next(src))?),
        InterfaceType::S32 => Val::S32(i32::linear_lift_from_flat(cx, ty, next(src))?),
        InterfaceType::U32 => Val::U32(u32::linear_lift_from_flat(cx, ty, next(src))?),
        InterfaceType::S64 => Val::S64(i64::linear_lift_from_flat(cx, ty, next(src))?),
        InterfaceType::U64 => Val::U64(u64::linear_lift_from_flat(cx, ty, next(src))?),
        InterfaceType::Float32 => Val::Float32(f32::linear_lift_from_flat(cx, ty, next(src))?),
        InterfaceType::Float64 => Val::Float64(f64::linear_lift_from_flat(cx, ty, next(src))?),
        InterfaceType::Char => Val::Char(char::linear_lift_from_flat(cx, ty, next(src))?),
        InterfaceType::Own(_) | InterfaceType::Borrow(_) => {
            Val::Resource(ResourceAny::linear_lift_from_flat(cx, ty, next(src))?)
        }
        InterfaceType::String => {
            let value = <crate::component::WasmStr as Lift>::linear_lift_from_flat(
                cx,
                ty,
                &[*next(src), *next(src)],
            )?;
            Val::String(value.to_string_accounted(cx)?)
        }
        InterfaceType::List(i) => {
            let (ptr, len) = lift_flat_pointer_pair(cx, src)?;
            load_list_accounted(cx, i, ptr, len)?
        }
        InterfaceType::Map(i) => {
            let (ptr, len) = lift_flat_pointer_pair(cx, src)?;
            load_map(cx, i, ptr, len)?
        }
        InterfaceType::Record(i) => {
            let fields = &cx.types[i].fields;
            cx.consume_fuel_array(fields.len(), size_of::<Val>())?;
            Val::Record(
                fields
                    .iter()
                    .map(|field| {
                        let val = Val::lift(cx, field.ty, src)?;
                        cx.consume_fuel(field.name.len())?;
                        Ok((
                            crate::component::dynamic_memory::text(memory.as_ref(), &field.name)?,
                            val,
                        ))
                    })
                    .collect_accounted(memory.as_ref())?,
            )
        }
        InterfaceType::Tuple(i) => {
            let types = &cx.types[i].types;
            cx.consume_fuel_array(types.len(), size_of::<Val>())?;
            Val::Tuple(
                types
                    .iter()
                    .map(|ty| Val::lift(cx, *ty, src))
                    .collect_accounted(memory.as_ref())?,
            )
        }
        InterfaceType::Variant(i) => {
            let vty = &cx.types[i];
            let (discriminant, value) = lift_variant(
                cx,
                cx.types.canonical_abi(&ty).flat_count(usize::MAX).unwrap(),
                vty.cases.values().copied(),
                src,
            )?;

            let (k, _) = vty.cases.get_index(discriminant as usize).unwrap();
            cx.consume_fuel(k.len())?;
            Val::Variant(
                crate::component::dynamic_memory::text(memory.as_ref(), k)?,
                value,
            )
        }
        InterfaceType::Enum(i) => {
            let ety = &cx.types[i];
            let (discriminant, _) = lift_variant(
                cx,
                cx.types.canonical_abi(&ty).flat_count(usize::MAX).unwrap(),
                ety.names.iter().map(|_| None),
                src,
            )?;

            let name = &ety.names[discriminant as usize];
            cx.consume_fuel(name.len())?;
            Val::Enum(crate::component::dynamic_memory::text(
                memory.as_ref(),
                name,
            )?)
        }
        InterfaceType::Option(i) => {
            let (_discriminant, value) = lift_variant(
                cx,
                cx.types.canonical_abi(&ty).flat_count(usize::MAX).unwrap(),
                [None, Some(cx.types[i].ty)].into_iter(),
                src,
            )?;

            Val::Option(value)
        }
        InterfaceType::Result(i) => {
            let result_ty = &cx.types[i];
            let (discriminant, value) = lift_variant(
                cx,
                cx.types.canonical_abi(&ty).flat_count(usize::MAX).unwrap(),
                [result_ty.ok, result_ty.err].into_iter(),
                src,
            )?;

            Val::Result(if discriminant == 0 {
                Ok(value)
            } else {
                Err(value)
            })
        }
        InterfaceType::Flags(i) => {
            let u32_count = cx.types.canonical_abi(&ty).flat_count(usize::MAX).unwrap();
            let ty = &cx.types[i];
            let mut flags = Vec::new();
            for i in 0..u32::try_from(u32_count).unwrap() {
                let bits = u32::linear_lift_from_flat(cx, InterfaceType::U32, next(src))?;
                push_flags(cx, ty, &mut flags, i * 32, bits)?;
            }

            Val::Flags(flags)
        }
        InterfaceType::Future(_) => {
            Val::Future(FutureAny::linear_lift_from_flat(cx, ty, next(src))?)
        }
        InterfaceType::Stream(_) => {
            Val::Stream(StreamAny::linear_lift_from_flat(cx, ty, next(src))?)
        }
        InterfaceType::ErrorContext(_) => {
            ErrorContext::linear_lift_from_flat(cx, ty, next(src))?.into_val()
        }
        InterfaceType::FixedLengthList(i) => {
            let number_elements = usize::try_from(cx.types[i].size)?;
            cx.consume_fuel_array(number_elements, size_of::<Val>())?;
            Val::FixedLengthList(
                (0..number_elements)
                    .map(|_| Val::lift(cx, cx.types[i].element, src))
                    .collect_accounted(memory.as_ref())?,
            )
        }
    })
}

/// Deserialize a value of this type from the heap.
fn load_inner(cx: &mut LiftContext<'_>, ty: InterfaceType, bytes: &[u8]) -> Result<Val> {
    supported(ty)?;
    let memory = cx.dynamic_memory.clone();
    Ok(match ty {
        InterfaceType::Bool => Val::Bool(bool::linear_lift_from_memory(cx, ty, bytes)?),
        InterfaceType::S8 => Val::S8(i8::linear_lift_from_memory(cx, ty, bytes)?),
        InterfaceType::U8 => Val::U8(u8::linear_lift_from_memory(cx, ty, bytes)?),
        InterfaceType::S16 => Val::S16(i16::linear_lift_from_memory(cx, ty, bytes)?),
        InterfaceType::U16 => Val::U16(u16::linear_lift_from_memory(cx, ty, bytes)?),
        InterfaceType::S32 => Val::S32(i32::linear_lift_from_memory(cx, ty, bytes)?),
        InterfaceType::U32 => Val::U32(u32::linear_lift_from_memory(cx, ty, bytes)?),
        InterfaceType::S64 => Val::S64(i64::linear_lift_from_memory(cx, ty, bytes)?),
        InterfaceType::U64 => Val::U64(u64::linear_lift_from_memory(cx, ty, bytes)?),
        InterfaceType::Float32 => Val::Float32(f32::linear_lift_from_memory(cx, ty, bytes)?),
        InterfaceType::Float64 => Val::Float64(f64::linear_lift_from_memory(cx, ty, bytes)?),
        InterfaceType::Char => Val::Char(char::linear_lift_from_memory(cx, ty, bytes)?),
        InterfaceType::String => {
            let value =
                <crate::component::WasmStr as Lift>::linear_lift_from_memory(cx, ty, bytes)?;
            Val::String(value.to_string_accounted(cx)?)
        }
        InterfaceType::Own(_) | InterfaceType::Borrow(_) => {
            Val::Resource(ResourceAny::linear_lift_from_memory(cx, ty, bytes)?)
        }
        InterfaceType::List(i) => {
            let (ptr, len) = load_flat_pointer_pair(bytes);
            load_list_accounted(cx, i, ptr, len)?
        }
        InterfaceType::Map(i) => {
            let (ptr, len) = load_flat_pointer_pair(bytes);
            load_map(cx, i, ptr, len)?
        }

        InterfaceType::Record(i) => {
            let mut offset = 0;
            let fields = cx.types[i].fields.iter();
            cx.consume_fuel_array(fields.len(), size_of::<Val>())?;
            Val::Record(
                fields
                    .map(|field| -> Result<(String, Val)> {
                        cx.consume_fuel(field.name.len())?;
                        let abi = cx.types.canonical_abi(&field.ty);
                        let offset = abi.next_field32(&mut offset);
                        let offset = usize::try_from(offset).unwrap();
                        let size = usize::try_from(abi.size32).unwrap();
                        Ok((
                            crate::component::dynamic_memory::text(memory.as_ref(), &field.name)?,
                            Val::load(cx, field.ty, &bytes[offset..][..size])?,
                        ))
                    })
                    .collect_accounted(memory.as_ref())?,
            )
        }
        InterfaceType::Tuple(i) => {
            let types = cx.types[i].types.iter().copied();
            cx.consume_fuel_array(types.len(), size_of::<Val>())?;
            let mut offset = 0;
            Val::Tuple(
                types
                    .map(|ty| {
                        let abi = cx.types.canonical_abi(&ty);
                        let offset = abi.next_field32(&mut offset);
                        let offset = usize::try_from(offset).unwrap();
                        let size = usize::try_from(abi.size32).unwrap();
                        Val::load(cx, ty, &bytes[offset..][..size])
                    })
                    .collect_accounted(memory.as_ref())?,
            )
        }
        InterfaceType::Variant(i) => {
            let ty = &cx.types[i];
            let (discriminant, value) =
                load_variant(cx, &ty.info, ty.cases.values().copied(), bytes)?;

            let (k, _) = ty.cases.get_index(discriminant as usize).unwrap();
            cx.consume_fuel(k.len())?;
            Val::Variant(
                crate::component::dynamic_memory::text(memory.as_ref(), k)?,
                value,
            )
        }
        InterfaceType::Enum(i) => {
            let ty = &cx.types[i];
            let (discriminant, _) =
                load_variant(cx, &ty.info, ty.names.iter().map(|_| None), bytes)?;

            let name = &ty.names[discriminant as usize];
            cx.consume_fuel(name.len())?;
            Val::Enum(crate::component::dynamic_memory::text(
                memory.as_ref(),
                name,
            )?)
        }
        InterfaceType::Option(i) => {
            let ty = &cx.types[i];
            let (_discriminant, value) =
                load_variant(cx, &ty.info, [None, Some(ty.ty)].into_iter(), bytes)?;

            Val::Option(value)
        }
        InterfaceType::Result(i) => {
            let ty = &cx.types[i];
            let (discriminant, value) =
                load_variant(cx, &ty.info, [ty.ok, ty.err].into_iter(), bytes)?;

            Val::Result(if discriminant == 0 {
                Ok(value)
            } else {
                Err(value)
            })
        }
        InterfaceType::Flags(i) => {
            let ty = &cx.types[i];
            let mut flags = Vec::new();
            match FlagsSize::from_count(ty.names.len()) {
                FlagsSize::Size0 => {}
                FlagsSize::Size1 => {
                    let bits = u8::linear_lift_from_memory(cx, InterfaceType::U8, bytes)?;
                    push_flags(cx, ty, &mut flags, 0, u32::from(bits))?;
                }
                FlagsSize::Size2 => {
                    let bits = u16::linear_lift_from_memory(cx, InterfaceType::U16, bytes)?;
                    push_flags(cx, ty, &mut flags, 0, u32::from(bits))?;
                }
                FlagsSize::Size4Plus(n) => {
                    for i in 0..n {
                        let bits = u32::linear_lift_from_memory(
                            cx,
                            InterfaceType::U32,
                            &bytes[usize::from(i) * 4..][..4],
                        )?;
                        push_flags(cx, ty, &mut flags, u32::from(i) * 32, bits)?;
                    }
                }
            }
            Val::Flags(flags)
        }
        InterfaceType::Future(_) => FutureAny::linear_lift_from_memory(cx, ty, bytes)?.into(),
        InterfaceType::Stream(_) => StreamAny::linear_lift_from_memory(cx, ty, bytes)?.into(),
        InterfaceType::ErrorContext(_) => {
            ErrorContext::linear_lift_from_memory(cx, ty, bytes)?.into_val()
        }
        InterfaceType::FixedLengthList(i) => {
            let element_type = cx.types[i].element;
            let abi = cx.types.canonical_abi(&element_type);
            let element_size = usize::try_from(abi.size32)?;
            let number_elements = usize::try_from(cx.types[i].size)?;

            match number_elements.checked_mul(element_size) {
                Some(total_size) if total_size <= bytes.len() => {
                    cx.consume_fuel_array(number_elements, size_of::<Val>())?;
                    Val::FixedLengthList(
                        (0..number_elements)
                            .map(|n| {
                                // the match already checked that the whole array fits into usize
                                let offset = element_size.wrapping_mul(n);
                                Val::load(cx, element_type, &bytes[offset..][..element_size])
                            })
                            .collect_accounted(memory.as_ref())?,
                    )
                }
                _ => bail!("fixed length list out of bounds of memory"),
            }
        }
    })
}

fn load_list_accounted(
    cx: &mut LiftContext<'_>,
    ty: TypeListIndex,
    ptr: usize,
    len: usize,
) -> Result<Val> {
    let memory = cx.dynamic_memory.clone();
    let elem = cx.types[ty].element;
    let abi = cx.types.canonical_abi(&elem);
    let element_size = usize::try_from(abi.size32).unwrap();
    let element_alignment = abi.align32;

    match len
        .checked_mul(element_size)
        .and_then(|len| ptr.checked_add(len))
    {
        Some(n) if n <= cx.memory().len() => cx.consume_fuel_array(len, size_of::<Val>())?,
        _ => bail!("list pointer/length out of bounds of memory"),
    }
    if ptr % usize::try_from(element_alignment)? != 0 {
        bail!("list pointer is not aligned")
    }

    Ok(Val::List(
        (0..len)
            .map(|index| {
                Val::load(
                    cx,
                    elem,
                    &cx.memory()[ptr + (index * element_size)..][..element_size],
                )
            })
            .collect_accounted(memory.as_ref())?,
    ))
}

pub(super) fn lift(
    cx: &mut LiftContext<'_>,
    ty: InterfaceType,
    src: &mut Iter<'_, ValRaw>,
) -> Result<Val> {
    ensure!(cx.dynamic_depth < 64, "dynamic-value-depth-limit");
    cx.dynamic_depth += 1;
    let result = lift_inner(cx, ty, src);
    cx.dynamic_depth -= 1;
    result
}
pub(super) fn load(cx: &mut LiftContext<'_>, ty: InterfaceType, bytes: &[u8]) -> Result<Val> {
    ensure!(cx.dynamic_depth < 64, "dynamic-value-depth-limit");
    cx.dynamic_depth += 1;
    let result = load_inner(cx, ty, bytes);
    cx.dynamic_depth -= 1;
    result
}
