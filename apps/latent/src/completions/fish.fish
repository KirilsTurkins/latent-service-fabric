
# Static positional choices from Clap; never invoke the product for completion.
function __latent_complete_positional
    set -l expected_count $argv[1]
    set -l depth $argv[2]
    set -e argv[1..2]
    set -l expected_path
    if test $depth -gt 0
        set expected_path $argv[1..$depth]
        set -e argv[1..$depth]
    end
    set -l words (commandline -opc)
    set -e words[1]
    argparse -i $argv -- $words 2>/dev/null; or return 1
    test (count $argv) -eq $expected_count; or return 1
    for part in $expected_path
        test "$argv[1]" = "$part"; or return 1
        set -e argv[1]
    end
    return 0
end
