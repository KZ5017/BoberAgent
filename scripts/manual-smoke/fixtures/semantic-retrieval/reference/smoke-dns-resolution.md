+++
id = "knowledge.smoke.dns-resolution"
version = 1
title = "DNS name resolution"
type = "reference"
status = "CANONICAL"
source_kind = "author_maintained"
domains = ["network"]
tags = ["manual-m18-smoke", "dns"]
technology = "dns"
protocol = "dns"
+++
# Resolving names

A DNS resolver answers questions about names and resource records. An absent record or a timeout
has a different meaning from a response containing an address.

## Resolver behavior

Compare authoritative and recursive answers when interpreting stale cache data. Preserve the
queried name, record type, server address, and response code as separate evidence.
