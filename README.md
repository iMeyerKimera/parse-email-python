Parse emails using python.

Notes:
------
1. RFC 822 forbids the use of some ascii characters, but these ascii characters
can be used in parsing of string without disturbances if they are encoded.
Regarding RFC 2047, non ascii text in the headers must be encoded.
RFC 2822 outlines the differences between the different header types
i.e all text fields like Subject or Address files, each with different encoding rules.

2. We'll be using the python email module by importing it. This module provides a
email.Header.decode_header() a header decoder function which decodes each atom and
returns a list of tuple(text,encoding), which has to be decoded and joined to
get the full text with the help of the getmailheader() function. And lastly for
the addresses, we'll utilize the email.utils.getaddresses() function, which splits the
addresses in a list of tuple (display-name, address). This needs to be decoded as well
and the addresses must match the RFC2822 syntax. The getmailaddresses() does all the work.

