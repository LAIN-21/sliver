# Area-specific agent instructions

[AGENTS.md](../../AGENTS.md) is the repository-wide constitution. Files in this directory add stricter constraints for one architectural lane.

Create an area file only when that code or architecture area actually exists. Do not add seller, catalog, payment, or database instructions in advance of real boundaries.

Area instructions may add constraints. They must not weaken repository-wide product, security, or architecture invariants.

## Current files

- [infrastructure.md](infrastructure.md)

## Future files

Add these only when the corresponding boundary is real:

- seller
- catalog
- transactions
- application API
- database
