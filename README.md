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

3. Today's emails include HTML formatted texts, pictures and other attachments.(Mail Parts)
MIME enables all mail parts to be mixed into a single mail. It should be
noted that MIME is complex and not all emails comply with the standards. With the
Python email library, emails can be split into parts applying the MIME philosophy.

4. Emails can be split into 3 categories.
- The message content. This is usually in plain text of HTML format.
- Data related to the message like background pictures and company logo.
- Attachments.

5. MIME doesn't clearly indicate which part is the message content.
The plain text, followed by the html version is usually at the top to allow easy
reading for the MIME unaware mail readers. Avoid using ordinary attachments
as the message email search_message_bodies()

6. We'll elaborate with code how different content can be mixed into a single email.
Email parts include  'text/plain', 'text/html', 'image/*', 'application/*' or 'multipart/*'
and together, they form a container. Containers can contain other containers.


