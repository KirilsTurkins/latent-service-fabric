    # Static Clap metadata; no invocation of latent, providers or remote discovery.
    $grammar = @@GRAMMAR@@ | ConvertFrom-Json -AsHashtable
    $command = @@ROOT@@
    $node = $grammar[$command]
    $pending = $null
    $position = 0
    $literal = $false
    foreach ($element in @($commandAst.CommandElements | Select-Object -Skip 1)) {
        if ($element.Extent.EndOffset -ge $cursorPosition) { break }
        # Reading the AST is not evaluating user input. In particular, never
        # expand a variable, subexpression or command substitution here.
        $token = $element.Extent.Text
        if ($element -is [StringConstantExpressionAst]) { $token = $element.Value }
        if ($null -ne $pending) { $pending = $null; continue }
        if (-not $literal -and $token -eq '--') { $literal = $true; continue }
        if (-not $literal -and $token.StartsWith('-')) {
            $parts = $token.Split('=', 2)
            if ($node.options.ContainsKey($parts[0])) {
                $option = $node.options[$parts[0]]
                if ($option.takes_value -and $parts.Count -eq 1) { $pending = $option }
            }
            continue
        }
        if (-not $literal -and $node.children.ContainsKey($token)) {
            $command = $node.children[$token]
            $node = $grammar[$command]
            $position = 0
        } else { $position++ }
    }
    $prefix = ''
    $fragment = $wordToComplete
    if (-not $literal -and $fragment.StartsWith('--') -and $fragment.Contains('=')) {
        $parts = $fragment.Split('=', 2)
        if ($node.options.ContainsKey($parts[0])) {
            $pending = $node.options[$parts[0]]
            $prefix = $parts[0] + '='
            $fragment = $parts[1]
        }
    }
    if ($null -eq $pending -and -not $fragment.StartsWith('-') -and $position -lt $node.positionals.Count) {
        $pending = $node.positionals[$position]
    }
    if ($null -ne $pending) {
        $fragment = $fragment.Trim([char[]]@('"', "'"))
        if ($pending.values.Count -gt 0) {
            foreach ($value in $pending.values) {
                if ($value.StartsWith($fragment, [StringComparison]::OrdinalIgnoreCase)) {
                    $text = $prefix + "'" + $value.Replace("'", "''") + "'"
                    [CompletionResult]::new($text, $value, [CompletionResultType]::ParameterValue, $value)
                }
            }
            return
        }
        if ($pending.path -ne '') {
            # FileSystem paths only: never enumerate another PowerShell provider
            # or an explicit UNC/network path. .NET receives literal path data.
            if ($PWD.Provider.Name -ne 'FileSystem' -or $fragment.StartsWith('\\') -or $fragment.StartsWith('//')) { return }
            $expanded = $fragment
            if ($expanded.StartsWith('~/') -or $expanded.StartsWith('~\')) {
                $expanded = [IO.Path]::Combine($HOME, $expanded.Substring(2))
            }
            try {
                $parent = [IO.Path]::GetDirectoryName($expanded)
                $leaf = [IO.Path]::GetFileName($expanded)
                $displayParent = $fragment.Substring(0, $fragment.Length - $leaf.Length)
                if ([string]::IsNullOrEmpty($parent)) { $parent = $PWD.Path }
                elseif (-not [IO.Path]::IsPathRooted($parent)) { $parent = [IO.Path]::Combine($PWD.Path, $parent) }
                foreach ($entry in @([IO.Directory]::EnumerateFileSystemEntries($parent) | Sort-Object)) {
                    $name = [IO.Path]::GetFileName($entry)
                    if (-not $name.StartsWith($leaf, [StringComparison]::OrdinalIgnoreCase)) { continue }
                    $directory = [IO.Directory]::Exists($entry)
                    if ($pending.path -eq 'directory' -and -not $directory) { continue }
                    $candidate = $displayParent + $name
                    if ($directory) { $candidate += [IO.Path]::DirectorySeparatorChar }
                    $text = $prefix + "'" + $candidate.Replace("'", "''") + "'"
                    [CompletionResult]::new($text, $name, [CompletionResultType]::ParameterValue, $candidate)
                }
            } catch { }
        }
        # Unknown IDs/URLs/secrets have no live or provider-backed suggestions.
        return
    }
