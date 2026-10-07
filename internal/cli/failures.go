package cli

import (
	"errors"
	"fmt"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// The client's own failures. Each
// says what happened between the client and the server, or to the answer on the client's
// side, and none concerns intent, a twin, a bundle or the host, which are the server's to
// refuse (Constitution XI). Each is the command's own document, in its own operation,
// status error, exit 2, with no step, rendered as every command's is; no sentence names
// either token.

// interruptUndelivered is an interrupt the server at address could not be sent: the answer
// was abandoned, and the command reports why as the answer cut short.
type interruptUndelivered struct {
	address string
	err     error
}

func (e *interruptUndelivered) Error() string { return e.err.Error() }

func (e *interruptUndelivered) Unwrap() error { return e.err }

// transportFailure is a failure between the client and the server as the command's own
// document. got is how far the answer had come, which says whether a run may have been
// started and whether it is named.
func transportFailure(op string, err error, got progress) error {
	rule, object, message := failureOf(op, err, got)
	return &result{doc: findings.RuleErrorDocument(op, nil, rule, object, message)}
}

// failureOf words one failure of the transport.
func failureOf(op string, err error, got progress) (rule, object, message string) {
	var (
		undelivered *interruptUndelivered
		unreachable *api.Unreachable
		cut         *api.Cut
		refused     *api.TokenRefused
		unknown     *api.VersionUnknown
		tooLarge    *api.TooLarge
		frame       *api.FrameTooLarge
		unreadable  *api.Unreadable
		unexpected  *api.Unexpected
	)
	switch {
	case errors.Is(err, api.ErrTokenUnset):
		return findings.RuleAPITokenRefused, api.EnvToken,
			api.EnvToken + " is not set; a client sends the API's token with every request, and nothing was sent"
	case errors.Is(err, api.ErrTokenUnsendable):
		return findings.RuleAPITokenRefused, api.EnvToken,
			api.EnvToken + " holds a character a request header cannot carry, such as a carriage return; nothing was sent"
	case errors.Is(err, api.ErrTokenTrailingBlank):
		return findings.RuleAPITokenRefused, api.EnvToken,
			api.EnvToken + " ends in a space or a tab, which a request header cannot carry; nothing was sent"
	// An interrupt that could not be delivered is the answer stopping, in the same three
	// shapes as an answer cut short: its address is the one the request went to.
	case errors.As(err, &undelivered):
		return findings.RuleAPIUnreachable, undelivered.address,
			stoppedAnswering(undelivered.address, undeliveredCause(undelivered.err), got)
	case errors.As(err, &cut):
		return findings.RuleAPIUnreachable, cut.Address, stoppedAnswering(cut.Address, cut.Cause.Error(), got)
	case errors.As(err, &unreachable):
		return findings.RuleAPIUnreachable, unreachable.Address,
			fmt.Sprintf("the API at %s cannot be reached: %v; fylgja serve runs on the lab host", unreachable.Address, unreachable.Cause)
	case errors.As(err, &refused):
		return findings.RuleAPITokenRefused, refused.Address,
			fmt.Sprintf("the API at %s refused this client's token; %s must be the token fylgja serve was started with",
				refused.Address, api.EnvToken)
	case errors.As(err, &unknown):
		return findings.RuleAPIVersionUnknown, unknown.Address,
			fmt.Sprintf("the API at %s serves version %s; this client speaks version %s", unknown.Address, unknown.Served, api.Version)
	case errors.As(err, &tooLarge):
		// The server's own sentence, naming its bound.
		return findings.RuleAPITransferTooLarge, op, tooLarge.Message
	case errors.As(err, &frame):
		return findings.RuleAPITransferTooLarge, op,
			fmt.Sprintf("the API at %s sent an answer frame larger than this client's bound of %d bytes (%s); nothing was written on this machine",
				frame.Address, frame.LimitBytes, mebibytes(frame.LimitBytes))
	case errors.As(err, &unreadable):
		return findings.RuleOperationFailed, op, unreadable.Error()
	case errors.As(err, &unexpected):
		return findings.RuleOperationFailed, op, unexpected.Error()
	}
	return findings.RuleOperationFailed, op, err.Error()
}

// stoppedAnswering is the answer that ended before its document, and what that leaves of a
// run: none before the server began to start one; one that may have been started once it
// had; and the run it named once it had named it, which goes on. Once an
// interrupt reached the server, the run was asked to cancel, or its start abandoned, and the
// sentence says so rather than that it was not cancelled.
func stoppedAnswering(address, cause string, got progress) string {
	message := fmt.Sprintf("the API at %s stopped answering before the command ended: %s", address, cause)
	switch {
	case got.run != nil && got.cancelAsked:
		message += fmt.Sprintf("; run %s %s was asked to cancel and goes on to its cleanup: fylgja twin show names it",
			got.run.WorkflowID, got.run.RunID)
	case got.run != nil:
		message += fmt.Sprintf("; run %s %s was not cancelled and goes on: fylgja twin show names it", got.run.WorkflowID, got.run.RunID)
	case got.started && got.cancelAsked:
		message += "; a run may have been started and was asked to cancel: fylgja twin show names it"
	case got.started:
		message += "; a run may have been started and was not cancelled: fylgja twin show names it"
	}
	return message
}

// undeliveredCause is why an interrupt did not arrive: the network's own error when nothing
// answered, and otherwise the fault's sentence.
func undeliveredCause(err error) string {
	var unreachable *api.Unreachable
	if errors.As(err, &unreachable) {
		return unreachable.Cause.Error()
	}
	return err.Error()
}

// mebibytes is a bound in the unit its sentence names beside the bytes: 64 MiB.
func mebibytes(n int64) string {
	return fmt.Sprintf("%d MiB", n>>20)
}
