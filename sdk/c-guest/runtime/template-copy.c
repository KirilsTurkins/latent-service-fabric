/* Keep the refusal in its own non-LTO translation unit. The authenticated
 * post-link transform replaces this body. Its callers must retain an ordinary
 * returning call: seeing the trap during optimization would make their success
 * paths unreachable even after the exported body is replaced.
 */
__attribute__((export_name("__lsf_c_template_copy")))
void __lsf_c_template_copy(void *destination) {
    (void)destination;
    __builtin_trap();
}
