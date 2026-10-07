package api

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"unicode"
)

// Client speaks the API to one server. It is built from the client's
// environment, FYLGJA_API_ADDRESS and FYLGJA_API_TOKEN, and reads no other variable.
//
// The token is read where each request is built and is never held: not in a field, not in
// an error. A Client printed with any verb shows none of it.
type Client struct {
	// MaxFrameBytes is the longest frame of an answer this client reads: api.MaxFrameBytes,
	// changed only by a test.
	MaxFrameBytes int64

	address string
	build   string
	base    *url.URL
	getenv  func(string) (string, bool)
	http    *http.Client
}

// ErrTokenUnset is a client whose environment holds no token: nothing is sent.
var ErrTokenUnset = errors.New(EnvToken + " is not set")

// ErrTokenUnsendable is a client whose token holds a byte no request header can carry, such
// as the carriage return a local/.env saved with CRLF line endings leaves on every value.
// net/http would refuse the header once the request was built, a fault the client would
// otherwise report as the server unreachable; it is refused here instead, and nothing is
// sent.
var ErrTokenUnsendable = errors.New(EnvToken + " holds a character a request header cannot carry")

// ErrTokenTrailingBlank is a client whose token ends in a space or a horizontal tab. net/http
// sends it, but a server's reader trims a header value's trailing whitespace (RFC 9110 §5.5)
// before the token is compared, so the server would refuse a token equal to its own and the
// client would report one that differs. It is refused here instead, and nothing is sent.
// A leading blank reaches the server whole, and is not refused.
var ErrTokenTrailingBlank = errors.New(EnvToken + " ends in a space or a tab, which a request header cannot carry")

// ErrStreamEnded is an interrupt for an answer that has ended: the client reads on to its
// document.
var ErrStreamEnded = errors.New("the answer the interrupt names has ended")

// NewClient is the client of the API at FYLGJA_API_ADDRESS, the default address when it is
// unset or empty: host:port, or an http:// or https:// URL for a proxy the operator runs.
// An unset or empty FYLGJA_API_TOKEN is ErrTokenUnset, one no header can carry is
// ErrTokenUnsendable, one that ends in a space or a tab is ErrTokenTrailingBlank, and for
// each nothing is dialled. build is the client's own --version, which a caller compares with
// the server's.
func NewClient(getenv func(string) (string, bool), build string) (*Client, error) {
	token, _ := getenv(EnvToken)
	if token == "" {
		return nil, ErrTokenUnset
	}
	if !headerValue(token) {
		return nil, ErrTokenUnsendable
	}
	if last := token[len(token)-1]; last == ' ' || last == '\t' {
		return nil, ErrTokenTrailingBlank
	}
	address, _ := getenv(EnvAddress)
	if address == "" {
		address = DefaultAddress
	}
	base, err := baseURL(address)
	if err != nil {
		return nil, &Unreachable{Address: shownAddress(address), Cause: err}
	}
	dialer := &net.Dialer{Timeout: DialTimeout}
	return &Client{
		MaxFrameBytes: MaxFrameBytes,
		address:       address,
		build:         build,
		base:          base,
		getenv:        getenv,
		http: &http.Client{
			Transport: &http.Transport{
				// The address is the operator's, proxy included: no variable of the
				// environment's reroutes it.
				Proxy:                 nil,
				DialContext:           dialer.DialContext,
				TLSHandshakeTimeout:   DialTimeout,
				ResponseHeaderTimeout: HeaderTimeout,
				ExpectContinueTimeout: ExpectContinueTimeout,
			},
			// The API never redirects (contracts/api.md, "The transport's statuses"), so a 3xx
			// is something else at the address, and its status is the answer: no request, and
			// no token, is sent to its Location, which net/http would hand the token to on any
			// port of the host and any subdomain of it (D-042).
			CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
		},
	}, nil
}

// baseURL is the server's root, from host:port or a URL. A value it refuses is refused whole,
// before anything is dialled, and its sentence names the value as shownAddress does: without
// a URL's user or password (Constitution X), since the API's token is the
// client's credential and an address carries none, and with no control character.
func baseURL(address string) (*url.URL, error) {
	shown := shownAddress(address)
	if withoutUserinfo(address) != address {
		return nil, fmt.Errorf("%s names a user or password, which %s never carries: it takes host:port or an http:// or https:// URL without one",
			shown, EnvAddress)
	}
	// No address holds a control character, such as the carriage return a local/.env saved
	// with CRLF line endings leaves on every value. The URL parser would refuse a host:port's
	// only once a request was built, a fault reported as the server unreachable.
	control := strings.IndexFunc(address, unicode.IsControl) >= 0
	if strings.HasPrefix(address, "http://") || strings.HasPrefix(address, "https://") {
		u, err := url.Parse(address)
		if control || err != nil || u.Host == "" || u.RawQuery != "" || u.Fragment != "" || u.User != nil ||
			(u.Port() != "" && !decimalPort(u.Port())) {
			return nil, fmt.Errorf("%s is not a URL of a server: %s takes host:port or an http:// or https:// URL", shown, EnvAddress)
		}
		u.Path = strings.TrimSuffix(u.Path, "/")
		return u, nil
	}
	// A host:port with no port would dial port 80, and one whose port is not a port number, or
	// with a path in it, fails only once dialled, as an invalid port: each is refused here.
	if _, port, err := net.SplitHostPort(address); err != nil || control || !decimalPort(port) || strings.Contains(address, "/") {
		return nil, fmt.Errorf("%s is not host:port: %s takes host:port or an http:// or https:// URL", shown, EnvAddress)
	}
	return &url.URL{Scheme: "http", Host: address}, nil
}

// decimalPort reports whether port is a port number written in decimal digits alone, 1 to
// 65535: net.SplitHostPort checks nothing of it, and a dial takes a service name such as
// http.
func decimalPort(port string) bool {
	if port == "" || strings.TrimLeft(port, "0123456789") != "" {
		return false
	}
	n, err := strconv.Atoi(port)
	return err == nil && n >= 1 && n <= 65535
}

// shownAddress is address as a sentence names it: without a URL's user or password, and, when
// it holds a control character, quoted as Go quotes a string, so that none reaches the
// output.
// An address the client takes holds none, and is named as it was given.
func shownAddress(address string) string {
	shown := withoutUserinfo(address)
	if strings.IndexFunc(shown, unicode.IsControl) >= 0 {
		return strconv.Quote(shown)
	}
	return shown
}

// headerValue reports whether v can be sent as a request header's value: no control byte but
// a horizontal tab, the rule net/http applies to every value it sends
// (golang.org/x/net/http/httpguts.ValidHeaderFieldValue, which this build does not import).
func headerValue(v string) bool {
	for i := 0; i < len(v); i++ {
		if b := v[i]; (b < ' ' && b != '\t') || b == 0x7f {
			return false
		}
	}
	return true
}

// withoutUserinfo is address with anything before an @ in its authority left out: a URL's
// user and password, which no sentence names.
func withoutUserinfo(address string) string {
	scheme, rest := "", address
	if i := strings.Index(address, "://"); i >= 0 {
		scheme, rest = address[:i+len("://")], address[i+len("://"):]
	}
	authority, tail := rest, ""
	if i := strings.IndexAny(rest, "/?#"); i >= 0 {
		authority, tail = rest[:i], rest[i:]
	}
	if i := strings.LastIndex(authority, "@"); i >= 0 {
		authority = authority[i+1:]
	}
	return scheme + authority + tail
}

// Address is the server's address as the client's environment gave it, as every sentence
// about the server names it.
func (c *Client) Address() string { return c.address }

// Build is the client's own --version, as NewClient was given it.
func (c *Client) Build() string { return c.build }

func (c *Client) url(path string) string {
	u := *c.base
	u.Path += path
	return u.String()
}

// request is a POST to path carrying the token, read from the environment here and nowhere
// else.
func (c *Client) request(ctx context.Context, path string, body io.Reader) (*http.Request, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.url(path), body)
	if err != nil {
		return nil, &Unreachable{Address: c.address, Cause: causeOf(err)}
	}
	token, _ := c.getenv(EnvToken)
	req.Header.Set("Authorization", "Bearer "+token)
	return req, nil
}

// Do sends op's request and returns its answer once the headers have arrived: under
// Fylgja-Stream when stream is given, and with Expect: 100-continue when it carries files,
// so a refused token costs no upload. The server's build is handed to onHeaders
// before any frame is read. Every fault of the transport is one of this package's error
// types.
func (c *Client) Do(ctx context.Context, op string, req Request, stream string, onHeaders func(build string)) (*Answer, error) {
	body, err := EncodeRequest(req)
	if err != nil {
		return nil, err
	}
	hreq, err := c.request(ctx, Path(op), bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	hreq.Header.Set("Content-Type", "application/json")
	if stream != "" {
		hreq.Header.Set(HeaderStream, stream)
	}
	if len(req.Files) > 0 {
		hreq.Header.Set("Expect", "100-continue")
	}
	resp, err := c.http.Do(hreq)
	if err != nil {
		return nil, &Unreachable{Address: c.address, Cause: causeOf(err)}
	}
	if resp.StatusCode != http.StatusOK {
		defer func() { _ = resp.Body.Close() }()
		return nil, c.fault(resp)
	}
	if resp.Header.Get(HeaderVersion) == "" {
		_ = resp.Body.Close()
		return nil, &Unreachable{Address: c.address, Cause: errNotTheAPI}
	}
	if onHeaders != nil {
		onHeaders(resp.Header.Get(HeaderBuild))
	}
	return &Answer{address: c.address, body: resp.Body, r: bufio.NewReader(resp.Body), max: c.MaxFrameBytes}, nil
}

// errNotTheAPI is an answer from something at the address that is not the API.
var errNotTheAPI = errors.New("what answers there is not the API: its answer names no " + HeaderVersion)

// Interrupt delivers the operator's interrupt to the answer stream names: nil when it was
// delivered, ErrStreamEnded when that answer has ended.
func (c *Client) Interrupt(ctx context.Context, stream string) error {
	req, err := c.request(ctx, InterruptPath(stream), http.NoBody)
	if err != nil {
		return err
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return &Unreachable{Address: c.address, Cause: causeOf(err)}
	}
	defer func() { _ = resp.Body.Close() }()
	switch {
	case resp.StatusCode == http.StatusNoContent:
		return nil
	case resp.StatusCode == http.StatusNotFound && resp.Header.Get(HeaderVersions) == "":
		return ErrStreamEnded
	}
	return c.fault(resp)
}

// fault is the error a status other than the answer's is.
func (c *Client) fault(resp *http.Response) error {
	switch resp.StatusCode {
	case http.StatusUnauthorized:
		return &TokenRefused{Address: c.address}
	case http.StatusNotFound:
		// A server that serves this client's own version and still has no such path is not a
		// version this client does not speak: the address leads somewhere under the server, a
		// prefix the server does not have, and the 404 is reported as it is.
		if served := resp.Header.Get(HeaderVersions); served != "" && !speaks(served) {
			return &VersionUnknown{Address: c.address, Served: served}
		}
	case http.StatusRequestEntityTooLarge:
		p := problemOf(resp)
		if p.Message == "" {
			p.Message = "the request is larger than this server's transfer bound; nothing was read or filed"
		}
		return &TooLarge{Message: p.Message}
	case http.StatusBadRequest:
		return &Unreadable{Address: c.address, Message: problemOf(resp).Message}
	}
	return &Unexpected{Address: c.address, Status: resp.Status}
}

// speaks is whether a Fylgja-Api-Versions list names this client's version.
func speaks(served string) bool {
	for _, v := range strings.Split(served, ",") {
		if strings.TrimSpace(v) == Version {
			return true
		}
	}
	return false
}

// problemOf reads a fault's body, as much of it as a problem can be.
func problemOf(resp *http.Response) Problem {
	var p Problem
	_ = json.NewDecoder(io.LimitReader(resp.Body, MaxProblemBytes)).Decode(&p)
	return p
}

// causeOf is a transport error without the request's URL, which names the operation and
// says nothing the address does not.
func causeOf(err error) error {
	var u *url.Error
	if errors.As(err, &u) {
		return u.Err
	}
	return err
}

// Answer is an answer's frames, read one at a time as they arrive.
type Answer struct {
	address string
	body    io.ReadCloser
	r       *bufio.Reader
	max     int64
	done    bool
}

// Next is the answer's next frame. After the document it is io.EOF. An answer that ends, or
// whose connection fails, before its document is *Cut; a line longer than the client's
// bound is *FrameTooLarge, and nothing more of the answer is read. A frame of a kind this
// build does not know is returned with no kind, for the caller to pass over.
func (a *Answer) Next() (Frame, error) {
	if a.done {
		return Frame{}, io.EOF
	}
	for {
		line, err := a.line()
		if err != nil {
			a.done = true
			_ = a.body.Close()
			return Frame{}, err
		}
		if len(bytes.TrimSpace(line)) == 0 {
			continue
		}
		var f Frame
		if err := json.Unmarshal(line, &f); err != nil {
			a.done = true
			_ = a.body.Close()
			return Frame{}, &Cut{Address: a.address, Cause: fmt.Errorf("a line of the answer is not a frame: %w", err)}
		}
		if f.Kind() == KindDocument {
			a.done = true
			_ = a.body.Close()
		}
		return f, nil
	}
}

// line reads one line, without its newline, no longer than the bound.
func (a *Answer) line() ([]byte, error) {
	var line []byte
	for {
		chunk, err := a.r.ReadSlice('\n')
		line = append(line, chunk...)
		content := int64(len(line))
		if err == nil {
			content--
		}
		if content > a.max {
			return nil, &FrameTooLarge{Address: a.address, LimitBytes: a.max}
		}
		switch {
		case err == nil:
			return line[:len(line)-1], nil
		case errors.Is(err, bufio.ErrBufferFull):
			continue
		case errors.Is(err, io.EOF):
			return nil, &Cut{Address: a.address, Cause: io.ErrUnexpectedEOF}
		default:
			return nil, &Cut{Address: a.address, Cause: err}
		}
	}
}

// Close lets go of an answer not read to its document.
func (a *Answer) Close() error {
	a.done = true
	return a.body.Close()
}

// The transport's faults. Each carries what the client's sentence needs,
// and none carries a token.

// Unreachable is an address where nothing answers, or where what answers is not the API.
type Unreachable struct {
	Address string
	// Cause is the network's error with the request's URL taken off.
	Cause error
}

func (e *Unreachable) Error() string {
	return fmt.Sprintf("the API at %s cannot be reached: %v", e.Address, e.Cause)
}

func (e *Unreachable) Unwrap() error { return e.Cause }

// TokenRefused is a 401: the server was started with another token.
type TokenRefused struct{ Address string }

func (e *TokenRefused) Error() string {
	return fmt.Sprintf("the API at %s refused this client's token", e.Address)
}

// VersionUnknown is a 404 naming the versions the server serves, none of them this
// client's.
type VersionUnknown struct {
	Address string
	// Served is the server's Fylgja-Api-Versions, as it gave them.
	Served string
}

func (e *VersionUnknown) Error() string {
	return fmt.Sprintf("the API at %s serves version %s; this client speaks version %s", e.Address, e.Served, Version)
}

// TooLarge is a 413: the request was over the server's transfer bound.
type TooLarge struct {
	// Message is the server's sentence, naming its bound.
	Message string
}

func (e *TooLarge) Error() string { return e.Message }

// Unreadable is a 400: the server could not read the request.
type Unreadable struct {
	Address string
	// Message is the server's sentence.
	Message string
}

func (e *Unreadable) Error() string {
	return fmt.Sprintf("the API at %s could not read this request: %s", e.Address, e.Message)
}

// Unexpected is a status the API does not answer with.
type Unexpected struct {
	Address string
	// Status is the status line's text, 500 Internal Server Error.
	Status string
}

func (e *Unexpected) Error() string {
	return fmt.Sprintf("the API at %s answered %s", e.Address, e.Status)
}

// Cut is an answer that ended before its document: the server stopped, or the connection
// was lost.
type Cut struct {
	Address string
	Cause   error
}

func (e *Cut) Error() string {
	return fmt.Sprintf("the API at %s stopped answering before the command ended: %v", e.Address, e.Cause)
}

func (e *Cut) Unwrap() error { return e.Cause }

// FrameTooLarge is a frame of the answer longer than the client's bound; the rest of the
// answer is left unread.
type FrameTooLarge struct {
	Address    string
	LimitBytes int64
}

func (e *FrameTooLarge) Error() string {
	return fmt.Sprintf("the API at %s sent an answer frame larger than this client's bound of %d bytes", e.Address, e.LimitBytes)
}
