"""Limited TLS symbol-marker attribution over the maintained format-3 replay."""
from tools.artifact_identity_evidence.heaptrack import Replay, numbers


class TlsAllocationReplay(Replay):
    def __init__(self):
        super().__init__()
        self.string_tags, self.ip_tags, self.trace_tags = [0], [0], [0]
        self.allocation_tags = []
        self.owner_live, self.owner_peak, self.owner_allocations = [0, 0], [0, 0], [0, 0]

    def record(self, line):
        super().record(line)
        if len(line) < 3:
            return
        kind, body = line[:1], line[2:]
        if kind == b"s":
            value = body.partition(b" ")[2]
            self.string_tags.append(int(b"14latent_streams9transport" in value)
                                    | (2 * int(b"14latent_streams3tls9configure" in value)))
        elif kind == b"i":
            values = numbers(body)
            functions = values[2:3] if len(values) == 3 else values[2::3]
            tag = 0
            for function in functions:
                tag |= self.string_tags[function]
            self.ip_tags.append(tag)
        elif kind == b"t":
            ip, parent = numbers(body, 2)
            self.trace_tags.append(self.ip_tags[ip] | self.trace_tags[parent])
        elif kind == b"a":
            _, trace = numbers(body, 2)
            self.allocation_tags.append(self.trace_tags[trace])
        elif kind in (b"+", b"-"):
            index, = numbers(body, 1)
            size = self.sizes[index]
            tag = self.allocation_tags[index]
            for owner in range(2):
                if tag & (1 << owner):
                    self.owner_live[owner] += size if kind == b"+" else -size
                    self.owner_peak[owner] = max(self.owner_peak[owner], self.owner_live[owner])
                    self.owner_allocations[owner] += kind == b"+"

    def observation(self):
        total = self.result()
        total.pop("command")
        return {"allAllocations": total,
                "transport": {"peakBytes": self.owner_peak[0], "remainingBytes": self.owner_live[0],
                              "allocationCalls": self.owner_allocations[0]},
                "trustConfiguration": {"peakBytes": self.owner_peak[1], "remainingBytes": self.owner_live[1],
                                       "allocationCalls": self.owner_allocations[1]},
                "fullAccountingQualified": False}
