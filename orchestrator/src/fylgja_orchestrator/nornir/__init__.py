"""The private branch's OSPF adjacency check: a Nornir inventory of a twin, read from its record and its bundle, and a
check that polls each device's OSPF state over Nornir's asyncio runner and judges it against the bundle's links."""
