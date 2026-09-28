package streams

import (
	"errors"
	"io"
	"net"
)

const (
	maxReplyLine  = 512 // Includes CRLF; this experiment does not negotiate extensions.
	maxReplyLines = 16
	maxReplyBytes = maxReplyLine * maxReplyLines
)

var errReplyEnvelope = errors.New("smtp-reply-envelope")

// smtpReplyEnvelope bounds the plaintext presented to net/textproto, including
// its accumulated multiline string. It is not a replacement SMTP client and
// never interprets reply codes as authorization, rollback or retry permission.
// The standard reader also accepts FTP-style unprefixed continuation lines;
// this deliberately narrower SMTP profile rejects them before parser growth.
// Only scalar state is retained, no copy of peer text or credentials.
type smtpReplyEnvelope struct {
	prefix                       [4]byte
	code                         [3]byte
	lineBytes, replyBytes, lines int
	previous                     byte
	continued, failed            bool
}

func (g *smtpReplyEnvelope) accept(bytes []byte) (int, error) {
	if g.failed {
		return 0, errReplyEnvelope
	}
	for i, b := range bytes {
		g.lineBytes++
		g.replyBytes++
		if g.lineBytes > maxReplyLine || g.replyBytes > maxReplyBytes || g.lines >= maxReplyLines {
			g.failed = true
			return i, errReplyEnvelope
		}
		if g.lineBytes <= len(g.prefix) {
			g.prefix[g.lineBytes-1] = b
		}
		if b == '\n' {
			bare := g.lineBytes == 5 && g.prefix[3] == '\r'
			code := [3]byte{g.prefix[0], g.prefix[1], g.prefix[2]}
			if g.previous != '\r' || g.lineBytes < 5 ||
				code[0] < '2' || code[0] > '5' || code[1] < '0' || code[1] > '9' || code[2] < '0' || code[2] > '9' ||
				(!bare && g.prefix[3] != ' ' && g.prefix[3] != '-') ||
				(g.continued && code != g.code) {
				g.failed = true
				return i, errReplyEnvelope
			}
			g.lines++
			g.code = code
			g.continued = !bare && g.prefix[3] == '-'
			if !g.continued {
				g.replyBytes, g.lines = 0, 0
			}
			g.lineBytes, g.prefix = 0, [4]byte{}
		}
		g.previous = b
	}
	return len(bytes), nil
}

// smtpReplyConn withholds each entire line until its CRLF and envelope are
// valid. Returning a partial invalid line plus an error is insufficient:
// bufio/textproto may treat the buffered prefix as a successful final line.
// One fixed line, no read-ahead queue, no detached worker. This belongs to the
// active operation; its storage is included in operationMetadata.
type smtpReplyConn struct {
	net.Conn
	envelope       smtpReplyEnvelope
	line           [maxReplyLine]byte
	offset, length int
	terminal       error
}

func (c *smtpReplyConn) clear()       { clear(c.line[:]); c.offset, c.length = 0, 0 }
func (c *smtpReplyConn) Close() error { c.clear(); return c.Conn.Close() }
func (c *smtpReplyConn) Write(b []byte) (int, error) {
	if c.terminal != nil {
		return 0, c.terminal
	}
	return c.Conn.Write(b)
}
func (c *smtpReplyConn) Read(b []byte) (int, error) {
	if len(b) == 0 {
		return 0, nil
	}
	if c.offset == c.length {
		c.clear()
		if c.terminal != nil {
			return 0, c.terminal
		}
		for {
			if c.length == len(c.line) {
				c.terminal = errReplyEnvelope
				break
			}
			n, err := c.Conn.Read(c.line[c.length : c.length+1])
			if n > 0 {
				if _, failure := c.envelope.accept(c.line[c.length : c.length+1]); failure != nil {
					c.terminal = failure
					break
				}
				c.length++
				if c.line[c.length-1] == '\n' {
					c.terminal = err
					break
				}
			}
			if err != nil {
				c.terminal = err
				break
			}
			if n == 0 {
				c.terminal = io.ErrNoProgress
				break
			}
		}
		if c.length == 0 || c.line[c.length-1] != '\n' {
			c.clear()
			return 0, c.terminal
		}
	}
	n := copy(b, c.line[c.offset:c.length])
	clear(c.line[c.offset : c.offset+n])
	c.offset += n
	return n, nil
}
