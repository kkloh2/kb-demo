"""Workflows: versioned JSON flows and their running instances. Standalone: it knows nothing about
approvals or any source system. Features register step types (what a step does) and end listeners
(what happens when a flow ends); the engine only runs the flow."""
