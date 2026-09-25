+++
id = "knowledge.smoke.http-service"
version = 1
title = "HTTP service response inspection"
type = "reference"
status = "CANONICAL"
source_kind = "author_maintained"
domains = ["web"]
tags = ["manual-m18-smoke", "http"]
technology = "http"
protocol = "http"
+++
# HTTP responses

An HTTP service may return a redirect, a content page, or an error status for a requested path.
Response headers and status codes are evidence about the web endpoint, not authentication policy
for a directory service.

## Service identification

Preserve the response metadata and compare it with the observed endpoint before assigning a
technology label. Do not infer a server product from a single generic error page.
