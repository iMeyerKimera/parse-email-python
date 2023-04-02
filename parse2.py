import sys, os, StringIO, re
import email, mimetypes
from email.utils import parseaddr
from email.header import decode_header

invalid_chards_in_filename = '<>:"/\\|?*\%\'' + \
                             reduce(lambda x, y: x + chr(y), range(32), '')
invalid_windows_name = \
    'CON PRN AUX NUL COM1 COM2 COM3 COM4 COM5 ' \
    'COM6 COM7 COM8 COM9 LPT1 LPT2 LPT3 LPT4 LPT5 LPT6 LPT7 LPT8 LPT9'.split()

# email address REGEX matching the RFC 2822 spec ..
# my $atom       = qr{[a-zA-Z0-9_!#\$\%&'*+/=?\^`{}~|\-]+};
# my $dot_atom   = qr{$atom(?:\.$atom)*};
# my $quoted     = qr{"(?:\\[^\r\n]|[^\\"])*"};
# my $local      = qr{(?:$dot_atom|$quoted)};
# my $domain_lit = qr{\[(?:\\\S|[\x21-\x5a\x5e-\x7e])*\]};
# my $domain     = qr{(?:$dot_atom|$domain_lit)};
# my $addr_spec  = qr{$local\@$domain};
#
# Python translation

atom_rfc2822 = r"[a-zA-Z0-9_!#\$\%&'*+/=?\^`{}~|\-]+"
atom_posfix_restricted = r"[a-zA-Z0-9_#\$&'*+/=?\^`{}~|\-]+"  # without '!' and '%'
atom = atom_rfc2822
dot_atom = atom + r"(?:\." + atom + ")*"
quoted = r'"(?:\\[^\r\n]|[^\\"])*"'
local = "(?:" + dot_atom + "|" + quoted + ")"
domain_lit = r"\[(?:\\\S|[\x21-\x5a\x5e-\x7e])*\]"
domain = "(?:" + dot_atom + "|" + domain_lit + ")"
addr_spec = local + "\@" + domain

email_address_re = re.compile('^' + addr_spec + '$')


class Attachment:
    def __init__(self, part, filename=None, type=None, payload=None, charset=None,
                 content_id=None, description=None, disposition=None,
                 sanitized_filename=None, is_body=None):
        self.part = part  # original python part
        self.filename = filename  # file name in unicode if any
        self.type = type  # the mime-type
        self.payload = payload  # the MIME decoded content
        self.charset = charset  # the charset if any
        self.description = description  # if any
        self.disposition = disposition  # 'inline', 'attachment', or None
        self.sanitized_filename = sanitized_filename  # cleanup your filename here (TODO)
        self.is_body = is_body  # usually in (None, 'text/plain' or 'text/html')
        self.content_id = content_id  # if any
        if self.content_id:
            # strip '<>' to ease search and replace in "root" content (TODO)
            if self.content_id.startswith('<') and self.content_id.endswith('>'):
                self.content_id = self.content_id[1:-1]


def getmailheader(header_text, default="ascii"):
    """Decode header_text if needed"""
    try:
        headers = decode_header(header_text)
    except email.Errors.HeaderParseError:
        # This' been appended already in email.base64mime.decode()
        # instead return a sanitized ascii string
        return header_text.encode('ascii', 'replace').decode('ascii')
    else:
        for k, (text, charset) in enumerate(headers):
            try:
                headers[k] = unicode(text, charset or default, errors='replace')
            except LookupError:
                # if the charset is unknown, force default
                headers[k] = unicode(text, default, errors='replace')
        return u"".join(headers)


def getmailaddresses(msg, name):
    """retrieve From:, To:, Cc: addresses"""
    addrs = email.utils.getaddresses(msg.get_all(name, []))
    for k, (name, addr) in enumerate(addrs):
        if not name and addr:
            # only one string! Is it the address or is it the name ?
            # use the same for both and see later
            name = addr
        try:
            # address must be ascii only
            addr = addr.encode('ascii')
        except UnicodeError:
            addr = ''
        else:
            # address must match address regex
            if not email_address_re.match(addr):
                addr = ''
        addrs[k] = (getmailheader(name), addr)
    return addrs


def get_filename(part):
    """Many mail user agents send attachments with the filename in
    the 'name' parameter of the 'content-type' header instead
    of in the 'filename' parameter of the 'content-disposition' header.
    """
    filename = part.get_param('filename', None, 'content-disposition')
    if not filename:
        filename = part.get_param('name', None)  # default is 'content-type'

    if filename:
        # RFC 2231 must be used to encode parameters inside MIME header
        filename = email.Utils.collapse_rfc2231_value(filename).strip()

    if filename and isinstance(filename, str):
        # But a lot of MUA erroneously use RFC 2047 instead of RFC 2231
        # in fact many developers  miss use RFC2047 here !!!
        filename = getmailheader(filename)

    return filename


def _search_message_bodies(bodies, part):
    """recursive search of the multiple version of the 'message' inside
    the the message structure of the email, used by search_message_bodies()"""

    type = part.get_content_type()
    if type.startswith('multipart/'):
        # explore only True 'multipart/*'
        # because 'messages/rfc822' are also python 'multipart'
        if type == 'multipart/related':
            # the first part or the one pointed by start
            start = part.get_param('start', None)
            related_type = part.get_param('type', None)
            for k, subpart in enumerate(part.get_payload()):
                if (not start and k == 0) or (start and start == subpart.get('Content-Id')):
                    _search_message_bodies(bodies, subpart)
                    return
        elif type == 'multipart/alternative':
            # all parts are candidates and latest is best
            for subpart in part.get_payload():
                _search_message_bodies(bodies, subpart)
        elif type in ('multipart/report', 'multipart/signed'):
            # only the first part is candidate
            try:
                subpart = part.get_payload()[0]
            except IndexError:
                return
            else:
                _search_message_bodies(bodies, subpart)
                return

        elif type == 'multipart/signed':
            # cannot handle this
            return

        else:
            # unknown types must be handled as 'multipart/mixed'
            # This is the piece of code that could probably be improved, I use a heuristic :
            # - if not already found, use first valid non 'attachment' parts found
            for subpart in part.get_payload():
                tmp_bodies = dict()
                _search_message_bodies(tmp_bodies, subpart)
                for l, m in tmp_bodies.iteritems():
                    if not subpart.get_param('attachment', None, 'content-disposition') == '':
                        # if not an attachment, initiate value if not already found
                        bodies.setdefault(l, m)
            return
    else:
        bodies[part.get_content_type().lower()] = part
        return

    return


def search_message_bodies(mail):
    """search message content into a mail"""
    bodies = dict()
    _search_message_bodies(bodies, mail)
    return bodies


def get_mail_contents(msg):
    """split an email in a list of attachments"""

    attachments = []

    # retrieve messages of the email
    bodies = search_message_bodies(msg)
    # reverse bodies dict
    parts = dict((m, k) for k, m in bodies.iteritems())

    # organize the stack to handle deep first search
    stack = [msg, ]
    while stack:
        part = stack.pop(0)
        type = part.get_content_type()
        if type.startswith('message/'):
            # ('message/delivery-status', 'message/rfc822', 'message/disposition-notification'):
            # I don't want to explore the tree deeper here and just save source using msg.as_string()
            # but I don't use msg.as_string() because I want to use mangle_from_=False
            from email.Generator import Generator

            fp = StringIO.StringIO()
            g = Generator(fp, mangle_from_=False)
            g.flatten(part, unixfrom=False)
            payload = fp.getvalue()
            filename = 'mail.eml'
            attachments.append(Attachment(part,
                                          filename=filename, type=type,
                                          payload=payload,
                                          charset=part.get_param('charset'),
                                          description=part.get('Content-Description')))
        elif part.is_multipart():
            # insert new parts at the beginning of the stack (deep first search)
            stack[:0] = part.get_payload()
        else:
            payload = part.get_payload(decode=True)
            charset = part.get_param('charset')
            filename = get_filename(part)

            disposition = None
            if part.get_param('inline', None, 'content-disposition') == '':
                disposition = 'inline'
            elif part.get_param('attachment', None, 'content-disposition') == '':
                disposition = 'attachment'

            attachments.append(Attachment(part, filename=filename,
                                          type=type, payload=payload,
                                          charset=charset, content_id=part.get('Content-Id'),
                                          description=part.get('Content-Description'),
                                          disposition=disposition, is_body=parts.get(part)))
    return attachments


def decode_text(payload, charset, default_charset):
    if charset:
        try:
            return payload.decode(charset), charset
        except UnicodeError:
            pass

    if default_charset and default_charset != 'auto':
        try:
            return payload.decode(default_charset), default_charset
        except UnicodeError:
            pass

    for chset in ['ascii', 'utf-8', 'utf-16', 'windows-1252', 'cp850']:
        try:
            return payload.decode(chset), chset
        except UnicodeError:
            pass

    return payload, None

if __name__ == "__main__":
    raw_version = """Delivered-To: example@example.com
Received: by 10.114.29.131 with SMTP id k3csp469759ldh;
        Fri, 19 Sep 2014 22:32:31 -0700 (PDT)
Return-Path: <3bhEdVAwJCKsVSLY-LNLOPXjRXLTW.NZXLcPXTVtnRXLTW.NZX@7SJ3MYH53AKEO4JRJXH7WZWH.apphosting.bounces.google.com>
Received-SPF: pass (google.com: domain of 3bhEdVAwJCKsVSLY-LNLOPXjRXLTW.NZXLcPXTVtnRXLTW.NZX@7SJ3MYH53AKEO4JRJXH7WZWH.apphosting.bounces.google.com designates 10.66.252.6 as permitted sender) client-ip=10.66.252.6
Authentication-Results: mr.google.com;
       spf=pass (google.com: domain of 3bhEdVAwJCKsVSLY-LNLOPXjRXLTW.NZXLcPXTVtnRXLTW.NZX@7SJ3MYH53AKEO4JRJXH7WZWH.apphosting.bounces.google.com designates 10.66.252.6 as permitted sender) smtp.mail=3bhEdVAwJCKsVSLY-LNLOPXjRXLTW.NZXLcPXTVtnRXLTW.NZX@7SJ3MYH53AKEO4JRJXH7WZWH.apphosting.bounces.google.com;
       dkim=pass header.i=@khanacademy.org
X-Received: from mr.google.com ([10.66.252.6])
        by 10.66.252.6 with SMTP id zo6mr19579994pac.40.1411191151359 (num_hops = 1);
        Fri, 19 Sep 2014 22:32:31 -0700 (PDT)
DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed;
        d=khanacademy.org; s=google;
        h=mime-version:message-id:date:subject:from:to:content-type;
        bh=HtWv9koaEpH5PWwPN+HkJIfWgZHCCN/dk8sqL7Arz6s=;
        b=WIKcgJ9BToxOiPHsfHslEQv5+oq9iqfQNtcmVROk0O7M+H7vhvscFN/JA2AV+NSHXG
         fBFuXqQmrjneZKJg5RY+EnDOGuuM/x8fMNzwGmgb5kdqxmYvWgnGbWFCpLSND9+JRs0k
         jtRIY8nxY/2xKRC050aWecFM/EPJ4/K6Go+k4=
MIME-Version: 1.0
X-Received: by 10.66.252.6 with SMTP id zo6mr13763216pac.40.1411191150169;
 Fri, 19 Sep 2014 22:32:30 -0700 (PDT)
X-Google-Appengine-App-Id: s~khan-academy
X-Google-Appengine-App-Id-Alias: khan-academy
Message-ID: <047d7b15ac0f374f4f0503788bb5@google.com>
Date: Sat, 20 Sep 2014 05:32:30 +0000
Subject: Your weekly progress summary on Khan Academy
From: Khan Academy <no-reply@khanacademy.org>
To: example@example.com
Content-Type: multipart/alternative; boundary=047d7b15ac0f374f220503788bb2

--047d7b15ac0f374f220503788bb2
Content-Type: text/plain; charset=ISO-8859-1; format=flowed; delsp=yes

Meyer Kimera,
Here's a look at what you achieved this week. Check it out, and keep
learning!

Recent Accomplishments
==================================
Points: 992
Badges earned:
Minutes on Khan Academy: 4
Mastered exercises: 0





Learn more today:

http://www.khanacademy.org/linkt?c=https%3A%2F%2Fwww.khanacademy.org%2F&bp=d2Vla2x5X3VzZXJfc3VtbWFyeV9lbWFpbF9vcGVu&bi=X2dhZV9iaW5nb19yYW5kb206Z3h6cjVGQk9OalFuLUFjQUlhUWVkaGt1TFEwcC15aVYweDZFa29kcg%3D%3D

If clicking doesn't seem to work, you can copy and paste the link into your
browser's address bar.


Onward!
Sal and the Khan Academy Team

P.S. You can unsubscribe from these emails at any time by following this
link:
https://www.khanacademy.org/settings/email?t1c=ag5zfmtoYW4tYWNhZGVteXJtCxIVVXNlckVtYWlsU3Vic2NyaXB0aW9uIlJlbWFpbF9zdWI6d2Vla2x5X3N1bW1hcnk6aWQ6aHR0cDovL2dvb2dsZWlkLmtoYW5hY2FkZW15Lm9yZy8xMDA4MjY4ODA4Mzk2OTIxMzI5NzI6DA

https://www.khanacademy.org/about/privacy-policy

--047d7b15ac0f374f220503788bb2
Content-Type: text/html; charset=UTF-8
Content-Transfer-Encoding: quoted-printable



<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">
<html lang=3D"en">
<head>
    <title>
Your weekly summary
</title>
    <meta content=3D"text/html; charset=3Dutf-8" http-equiv=3D"content-type=
">
    <meta http-equiv=3D"X-UA-Compatible" content=3D"IE=3Dedge">
</head>
<body>
   =20
   =20
   =20
   =20

   =20
<table width=3D"100%" cellpadding=3D"0" cellspacing=3D"0" border=3D"0" bgco=
lor=3D"#2c3747" style=3D"background-color: #e2e2e2; font-size: 12px;font-fa=
mily: Helvetica, Arial, Geneva, sans-serif;">

<!-- HEADER -->

<tr>
  <td>
    <table cellpadding=3D"0" cellspacing=3D"0" border=3D"0" width=3D"600" a=
lign=3D"center" bgcolor=3D"#e2e2e2">

<!-- HEADER CONTENT CONTAINER -->
<tr>
  <td>
    <table cellpadding=3D"0" cellspacing=3D"0" border=3D"0" width=3D"600" a=
lign=3D"center">

<!-- INSIDE CONTENT WRAP-->
<tr>
  <td>
    <table cellpadding=3D"0" cellspacing=3D"0" border=3D"0" width=3D"600" a=
lign=3D"center">

<!-- Logo/Date Container -->
      <tr>
        <td>
          <table cellpadding=3D"0" cellspacing=3D"0" border=3D"0" width=3D"=
600" align=3D"center" bgcolor=3D"#2c3747" style=3D"margin-top: 20px">

<!--LOGO -->
            <tr>
              <td>
                <table cellpadding=3D"10" cellspacing=3D"0" border=3D"0" wi=
dth=3D"600" align=3D"center">
                  <tr>
                  <td align=3D"center" width=3D"175" valign=3D"middle">
                   =20
<a href=3D"https://www.khanacademy.org">
    <img
        src=3D"http://www.khanacademy.org/imaget/ka-email-banner-logo.png?c=
ode=3Dd2Vla2x5X3VzZXJfc3VtbWFyeV9lbWFpbF9vcGVuCl9nYWVfYmluZ29fcmFuZG9tOmd4e=
nI1RkJPTmpRbi1BY0FJYVFlZGhrdUxRMHAteWlWMHg2RWtvZHI=3D"
        width=3D"194"
        border=3D"0"
        height=3D"20"
        alt=3D"Khan Academy">
</a>

                  </td>
                  </tr>
                </table>
              </td>
            </tr>

          </table>
        </td>
      </tr>
<!-- END Logo/Date Container -->

    </table>
   </td>
 </tr>
<!-- END INSIDE CONTENT WRAP -->

    </table>
  </td>
</tr>
<!-- END HEADER -->

   </table>
  </td>
</tr>
<!-- END HEADER CONTENT CONTAINER -->


<!-- =3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=
=3D=3D=3D=3D=3D=3D CONTENT =3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=
=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D=3D -->


<!-- CONTENT CONTAINER -->
<tr>
  <td>
    <table cellpadding=3D"0" cellspacing=3D"0" border=3D"0" width=3D"600" a=
lign=3D"center">

<!-- CONTENT -->
<tr>
  <td>
    <table cellpadding=3D"0" cellspacing=3D"0" width=3D"600" align=3D"cente=
r" style=3D"border-width: 1px; border-spacing: 0px; border-style: solid; bo=
rder-color: #cccccc; border-collapse: collapse; background-color: #ffffff;"=
>

<!-- INSIDE CONTENT WRAP-->
<tr>
    <td style=3D"background-color: #f7f7f7; font-family: 'Helvetica Neue', =
Calibri, Helvetica, Arial, sans-serif; font-size: 15px; color: black; borde=
r-bottom: 1px solid #ddd">
        <table cellpadding=3D"0" cellspacing=3D"0" border=3D"0" width=3D"50=
0" align=3D"center" style=3D"margin: 28px 50px; font-size: 15px; line-heigh=
t: 24px; ">
            <tbody>
                <tr>
                    <td>
                   =20
<p>
    <strong>Meyer Kimera,</strong>
    <br>
   =20
        Here&#39;s a look at what you achieved this week. Check it out, and=
 keep learning!
   =20
</p>



<p style=3D"font-family: 'Helvetica Neue', Calibri, Helvetica, Arial, sans-=
serif; font-size: 16px; line-height: 24px; color: #666; margin: 0 0 10px; m=
argin: 5px 0 0 0; text-align: center;">
   =20
    <a href=3D"http://www.khanacademy.org/linkt?c=3Dhttps%3A%2F%2Fwww.khana=
cademy.org%2F&amp;bp=3Dd2Vla2x5X3VzZXJfc3VtbWFyeV9lbWFpbF9vcGVu&amp;bi=3DX2=
dhZV9iaW5nb19yYW5kb206Z3h6cjVGQk9OalFuLUFjQUlhUWVkaGt1TFEwcC15aVYweDZFa29kc=
g%3D%3D" style=3D"font-family: 'Helvetica Neue', Calibri, Helvetica, Arial,=
 sans-serif; border: 1px solid #76a015; background-color: #7fac05; color: w=
hite; display: inline-block; padding: 0 32px; margin: 0; border-radius: 5px=
; font-size: 16px; line-height: 40px; text-decoration: none; cursor: pointe=
r;width: 436px">Learn more today</a>

</p>



                    </td>
                </tr>
            </tbody>
        </table>
    </td>
</tr>
<tr>
    <td>
        <table cellpadding=3D"0" cellspacing=3D"0" border=3D"0" width=3D"50=
0" align=3D"center" style=3D"margin: 10px 50px">
            <tbody>
                <tr>
                    <td>
                   =20


<table style=3D"margin: 0 auto;">
  <tr>
   =20
    <td style=3D"text-align: center; padding: 0 20px;">
     =20
        <span style=3D"font-family: 'Helvetica Neue', Calibri, Helvetica, A=
rial, sans-serif; font-weight: bold; font-size: 16px; color: #333; margin: =
40px 0 10px; text-transform: uppercase; display: block; margin-top: 10px;">
    Last Week
</span >
     =20
      <span style=3D"font-size: 52px; background: #0c6d92; color: #fff; lin=
e-height: 90px; border-radius: 10px; padding: 5px 10px;">
        <span style=3D"font-size: 30px; vertical-align: top">+ </span>
        992
      </span>
      <div style=3D"font-size: 14px; text-transform: uppercase; color: #888=
; text-align: center">
          energy points
      </div>
    <td>
   =20
  </tr>
</table>


<table width=3D"500" cellspacing=3D"0" cellpadding=3D"5" border=3D"0" style=
=3D"font-family: 'Helvetica Neue', Calibri, Helvetica, Arial, sans-serif; f=
ont-size: 14px;">
    <tr>
        <td style=3D"text-align: center;">
        <table cellspacing=3D"0" cellpadding=3D"5" border=3D"0" style=3D"ma=
rgin: 0 auto; width: 100%">
       =20
           =20
            <tr>
              <td width=3D"50%" style=3D"text-align: center; padding-bottom=
: 5px;" valign=3D"top">
                  <img src=3D"https://www.kastatic.org/images/badges/moon/r=
edwood-512x512.png" style=3D"vertical-align: middle; width: 100px; height: =
100px;">
                  <div style=3D"color: #444; width: 180px; margin: 5px auto=
;">Redwood</div>
              </td>
            </tr>
       =20
        </table>
        </td>
    </tr>
</table>



  <table width=3D"500" cellspacing=3D"0" cellpadding=3D"5" border=3D"0" sty=
le=3D"font-family: 'Helvetica Neue', Calibri, Helvetica, Arial, sans-serif;=
 border-top: 1px solid #eee; font-size: 14px; padding-top: 20px; margin-top=
: 20px;">
      <tr>
          <td style=3D"text-align: center;" colspan=3D"6">
            <span style=3D"font-family: 'Helvetica Neue', Calibri, Helvetic=
a, Arial, sans-serif; font-weight: bold; font-size: 16px; color: #333; marg=
in: 40px 0 10px; text-transform: uppercase;">
    You&#39;re close to earning
</span >
          </td>
      </tr>
      <tr>
          <td>
          <table cellspacing=3D"0" cellpadding=3D"5" border=3D"0" style=3D"=
margin: 0 auto; width: 362px">
         =20
             =20
              <tr>
                <td width=3D"105" style=3D"text-align: center; padding-bott=
om: 5px;" valign=3D"top">
                  <a href=3D"http://www.khanacademy.org/linkt?badge=3Dhang-=
ten&amp;c=3Dhttps%3A%2F%2Fwww.khanacademy.org%2F&amp;bp=3Dd2Vla2x5X3VzZXJfc=
3VtbWFyeV9lbWFpbF9vcGVu&amp;bi=3DX2dhZV9iaW5nb19yYW5kb206Z3h6cjVGQk9OalFuLU=
FjQUlhUWVkaGt1TFEwcC15aVYweDZFa29kcg%3D%3D">
                    <img src=3D"https://www.kastatic.org/images/badges/mete=
orite/hang-ten-512x512.png" style=3D"vertical-align: middle; width: 100px; =
height: 100px; opacity: 0.6">
                  </a>
                </td>
                <td style=3D"padding-bottom: 5px; padding-left: 10px;">
                  <div style=3D"line-height: 24px;">
                    <a href=3D"http://www.khanacademy.org/linkt?badge=3Dhan=
g-ten&amp;c=3Dhttps%3A%2F%2Fwww.khanacademy.org%2F&amp;bp=3Dd2Vla2x5X3VzZXJ=
fc3VtbWFyeV9lbWFpbF9vcGVu&amp;bi=3DX2dhZV9iaW5nb19yYW5kb206Z3h6cjVGQk9OalFu=
LUFjQUlhUWVkaGt1TFEwcC15aVYweDZFa29kcg%3D%3D" style=3D"color: #444; text-de=
coration: none">Hang Ten</a>
                  </div>
                  <div style=3D"font-style: italic; font-size: 14px; font-w=
eight: bold;">
                    <a href=3D"http://www.khanacademy.org/linkt?badge=3Dhan=
g-ten&amp;c=3Dhttps%3A%2F%2Fwww.khanacademy.org%2F&amp;bp=3Dd2Vla2x5X3VzZXJ=
fc3VtbWFyeV9lbWFpbF9vcGVu&amp;bi=3DX2dhZV9iaW5nb19yYW5kb206Z3h6cjVGQk9OalFu=
LUFjQUlhUWVkaGt1TFEwcC15aVYweDZFa29kcg%3D%3D" style=3D"color: #444; text-de=
coration: none">Finish 2 more mastery challenges</a>
                  </div>
                </td>
              </tr>
         =20
          </table>
          </td>
      </tr>
  </table>

 =20
   =20
    <p style=3D"font-family: 'Helvetica Neue', Calibri, Helvetica, Arial, s=
ans-serif; font-size: 16px; line-height: 24px; color: #666; margin: 0 0 10p=
x; margin: 5px 0 0 0; text-align: center;">
   =20
        <a href=3D"http://www.khanacademy.org/linkt?c=3Dhttps%3A%2F%2Fwww.k=
hanacademy.org%2F&amp;bp=3Dd2Vla2x5X3VzZXJfc3VtbWFyeV9lbWFpbF9vcGVu&amp;bi=
=3DX2dhZV9iaW5nb19yYW5kb206Z3h6cjVGQk9OalFuLUFjQUlhUWVkaGt1TFEwcC15aVYweDZF=
a29kcg%3D%3D" style=3D"font-family: 'Helvetica Neue', Calibri, Helvetica, A=
rial, sans-serif; border: 1px solid #76a015; background-color: #7fac05; col=
or: white; display: inline-block; padding: 0 32px; margin: 0; border-radius=
: 5px; font-size: 16px; line-height: 40px; text-decoration: none; cursor: p=
ointer;width: 362px; padding: 0">Earn this badge now</a>
   =20
</p>
 =20



<p style=3D"font-family: 'Helvetica Neue', Calibri, Helvetica, Arial, sans-=
serif; font-size: 16px; line-height: 24px; color: #666; margin: 0 0 10px; m=
argin-top: 20px; padding-top: 20px; border-top: 1px solid #eee; text-align:=
 center;">
   =20
   =20
        <span style=3D"font-family: 'Helvetica Neue', Calibri, Helvetica, A=
rial, sans-serif; font-weight: bold; font-size: 16px; color: #333; margin: =
40px 0 10px; text-transform: uppercase">
    Recent activity
</span >
   =20

</p>

<table width=3D"500" cellspacing=3D"0" cellpadding=3D"0" border=3D"0" style=
=3D"font-family: 'Helvetica Neue', Calibri, Helvetica, Arial, sans-serif; t=
able-layout: fixed; font-size: 14px; margin-top: 20px; margin-bottom: 20px;=
">
    <tr valign=3D"top">
        <td style=3D"border-top: 1px solid #ddd; padding: 8px;">
            <table cellspacing=3D"0" cellpadding=3D"0" style=3D"color: #333=
333; font-size: 12px;">
               =20
                   =20
    <tr>
       =20
        <td width=3D"15" style=3D"border-bottom: 1px solid #DDDDDD;">
           =20
    <span style=3D"margin: 2px; color: #888">=E2=96=B6</span>

        </td>

       =20
        <td width=3D"255" style=3D"padding: 10px; border-bottom: 1px solid =
#DDDDDD;">
            <span style=3D"color: #333333; text-decoration: none;">
                What is Programming?
            </span>

       =20
        <td align=3D"right" width=3D"170" style=3D"padding: 10px; border-bo=
ttom: 1px solid #DDDDDD;">
           =20
              3
              minutes
           =20
           =20
        </td>
    </tr>

               =20
                   =20
    <tr>
       =20
        <td width=3D"15" style=3D"border-bottom: 1px solid #DDDDDD;">
           =20
    <span style=3D"margin: 2px; color: #888">=E2=96=B6</span>

        </td>

       =20
        <td width=3D"255" style=3D"padding: 10px; border-bottom: 1px solid =
#DDDDDD;">
            <span style=3D"color: #333333; text-decoration: none;">
                What is Programming?
            </span>

       =20
        <td align=3D"right" width=3D"170" style=3D"padding: 10px; border-bo=
ttom: 1px solid #DDDDDD;">
           =20
              0
              minutes
           =20
           =20
        </td>
    </tr>

               =20
                   =20
    <tr>
       =20
        <td width=3D"15" style=3D"border-bottom: 1px solid #DDDDDD;">
           =20
    <span style=3D"margin: 2px; color: #888">=E2=96=B6</span>

        </td>

       =20
        <td width=3D"255" style=3D"padding: 10px; border-bottom: 1px solid =
#DDDDDD;">
            <span style=3D"color: #333333; text-decoration: none;">
                Distance in the metric system
            </span>

       =20
        <td align=3D"right" width=3D"170" style=3D"padding: 10px; border-bo=
ttom: 1px solid #DDDDDD;">
           =20
              3
              minutes
           =20
           =20
        </td>
    </tr>

               =20
            </table>
            <table cellspacing=3D"0" cellpadding=3D"10" width=3D"100%">
                <tr>
                    <td valign=3D"middle" align=3D"center" style=3D"font-si=
ze: 13px; text-align: center">
                          <a style=3D"color: #333333" href=3D"http://www.kh=
anacademy.org/linkt?c=3Dhttps%3A%2F%2Fwww.khanacademy.org%2Fprofile%2FiMeye=
rKimera%2Fvital-statistics&amp;bp=3Dd2Vla2x5X3VzZXJfc3VtbWFyeV9lbWFpbF9vcGV=
u&amp;bi=3DX2dhZV9iaW5nb19yYW5kb206Z3h6cjVGQk9OalFuLUFjQUlhUWVkaGt1TFEwcC15=
aVYweDZFa29kcg%3D%3D">
                             =20
                                  View the full report
                             =20
                          </a>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
</table>




                    </td>
                </tr>
            </tbody>
        </table>
    </td>
</tr>
<tr>
    <td style=3D"background-color: #f7f7f7; font-family: 'Helvetica Neue', =
Calibri, Helvetica, Arial, sans-serif; font-size: 15px; color: black; borde=
r-top: 1px solid #ddd">
        <table cellpadding=3D"0" cellspacing=3D"0" border=3D"0" width=3D"50=
0" align=3D"center" style=3D"margin: 28px 50px; font-size: 15px; line-heigh=
t: 24px; ">
            <tbody>
                <tr>
                    <td>
                       =20
<a href=3D"http://www.khanacademy.org/linkt?c=3Dhttps%3A%2F%2Fwww.khanacade=
my.org%2F&amp;bp=3Dd2Vla2x5X3VzZXJfc3VtbWFyeV9lbWFpbF9vcGVu&amp;bi=3DX2dhZV=
9iaW5nb19yYW5kb206Z3h6cjVGQk9OalFuLUFjQUlhUWVkaGt1TFEwcC15aVYweDZFa29kcg%3D=
%3D" style=3D"font-family: 'Helvetica Neue', Calibri, Helvetica, Arial, san=
s-serif; border: 1px solid #76a015; background-color: #7fac05; color: white=
; display: inline-block; padding: 0 32px; margin: 0; border-radius: 5px; fo=
nt-size: 16px; line-height: 40px; text-decoration: none; cursor: pointer;wi=
dth: 436px; text-align: center">Learn more today</a>

                    </td>
                </tr>
            </tbody>
        </table>
    </td>
</tr>
<!-- END INSIDE CONTENT WRAP -->

    </table>
  </td>
</tr>
<!-- END CONTENT -->

    </table>
  </td>
</tr>
<!-- END CONTENT CONTAINER -->

<!-- BEGIN FOOTER CONTENT CONTAINER -->
<tr>
  <td>
    <table cellpadding=3D"10" cellspacing=3D"0" border=3D"0" width=3D"600" =
align=3D"center" bgcolor=3D"#e2e2e2" style=3D"font-size: 12px;font-family: =
Helvetica, Arial, Geneva, sans-serif;">
        <tr>
            <td>
              <table cellpadding=3D"0" cellspacing=3D"5" border=3D"0" width=
=3D"580" align=3D"center">

                <tr>
                  <td align=3D"center">
                   =20
<p style=3D"font-family: 'Helvetica Neue', Calibri, Helvetica, Arial, sans-=
serif; font-weight: normal; font-size: 10px; color: #666;">
   =20
    This message was sent to <a href=3D"mailto:example@example.com" target=
=3D"_blank" style=3D"font-family: 'Helvetica Neue', Calibri, Helvetica, Ari=
al, sans-serif; font-size: 10px; font-weight: normal; color: #678d00; text-=
decoration: none;">example@example.com</a>.
    You may <a href=3D"https://www.khanacademy.org/settings/email?t1c=3Dag5=
zfmtoYW4tYWNhZGVteXJtCxIVVXNlckVtYWlsU3Vic2NyaXB0aW9uIlJlbWFpbF9zdWI6d2Vla2=
x5X3N1bW1hcnk6aWQ6aHR0cDovL2dvb2dsZWlkLmtoYW5hY2FkZW15Lm9yZy8xMDA4MjY4ODA4M=
zk2OTIxMzI5NzI6DA" target=3D"_blank" style=3D"font-family: 'Helvetica Neue'=
, Calibri, Helvetica, Arial, sans-serif; font-size: 10px; font-weight: norm=
al; color: #678d00; text-decoration: none;">unsubscribe from these emails</=
a>
    at any time. Please add <a href=3D"mailto:no-reply@khanacademy.org" tar=
get=3D"_blank" style=3D"font-family: 'Helvetica Neue', Calibri, Helvetica, =
Arial, sans-serif; font-size: 10px; font-weight: normal; color: #678d00; te=
xt-decoration: none;">no-reply@khanacademy.org</a>
    to your address book to ensure our emails are delivered
    correctly.

</p>
<p style=3D"font-family: 'Helvetica Neue', Calibri, Helvetica, Arial, sans-=
serif; font-weight: normal; font-size: 10px; color: #666;">
   =20
    <a href=3D"https://www.khanacademy.org/about/privacy-policy" target=3D"=
_blank" style=3D"font-family: 'Helvetica Neue', Calibri, Helvetica, Arial, =
sans-serif; font-size: 10px; font-weight: normal; color: #678d00; text-deco=
ration: none;">Privacy Policy</a>
    | <a href=3D"https://www.khanacademy.org/about/tos" target=3D"_blank" s=
tyle=3D"font-family: 'Helvetica Neue', Calibri, Helvetica, Arial, sans-seri=
f; font-size: 10px; font-weight: normal; color: #678d00; text-decoration: n=
one;">Terms of Service</a>

</p>

                  </td>
                </tr>
                <tr>
                  <!-- COMPANY ADDRESS -->
                  <td align=3D"center" style=3D"font-weight:normal; vertica=
l-align:middle; color:#6a6a6a; font-size: 10px"><br />
                      P.O. Box 1630, Mountain View, CA 94042
                  </td>
                </tr>
      </table>
    </td>
  </tr>
<!-- END FOOTER CONTENT CONTAINER -->

</table><!--END WRAPPER-->

</body>
</html>
--047d7b15ac0f374f220503788bb2--

"""
    if len(sys.argv)>1:
        raw=open(sys.argv[1]).read()

    msg=email.message_from_string(raw_version)
    attachments=get_mail_contents(msg)

    subject = getmailheader(msg.get('Subject', ''))
    from_ = getmailaddresses(msg, 'from')
    from_ = ('', '') if not from_ else from_[0]
    tos = getmailaddresses(msg, 'to')

    print 'Subject: %r' % subject
    print 'From: %r' % (from_, )
    print 'To: %r' % (tos, )

    for attach in attachments:
        # dont forget to sanitize 'filename' and be carefull
        # for filename collision, too before saving :
        print '\tfilename=%r is_body=%s type=%s charset=%s desc=%s size=%d' %\
            (attach.filename, attach.is_body, attach.type, attach.charset,
             attach.description, 0 if attach.payload==None else len(attach.payload))

        if attach.is_body=='text/plain':
            # print first 5 lines
            payload, used_charset=decode_text(attach.payload, attach.charset, 'auto')
            for line in payload.split('\n')[:55555]:
                if line:
                    print '\t\t', line
