// Package leaky is a client that reaches the core around the API: the fixture
// internal/compiler's TestClientReachesTheCoreThroughTheAPIAlone must fail.
// It is under testdata, so no build of the
// module compiles it.
package leaky

import (
	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/stage"
)

// Compile would read and compile in the client's own process.
var Compile = stage.Compile

// Address is what a client that kept to the API would have read.
const Address = api.DefaultAddress
