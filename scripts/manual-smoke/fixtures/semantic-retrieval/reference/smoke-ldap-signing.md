+++
id = "knowledge.smoke.ldap-signing"
version = 1
title = "Directory authentication and LDAP signing"
type = "reference"
status = "CANONICAL"
source_kind = "author_maintained"
domains = ["identity"]
tags = ["manual-m18-smoke", "ldap"]
technology = "ldap"
protocol = "ldap"
+++
# Directory authentication

Directory bind requests can fail when the server requires integrity protection on the connection.
This is a protocol requirement, not proof that an account name or password is wrong.

## LDAP signing requirement

An LDAP server configured to require signing rejects unsigned authentication traffic. A client
must negotiate signed communication or use a suitably protected channel before the bind can be
accepted. A failed unsigned bind should be investigated as a transport-security mismatch.

## Evidence interpretation

Record the bind response and connection settings separately. A rejected unsigned bind does not
by itself establish whether the supplied identity is valid.
