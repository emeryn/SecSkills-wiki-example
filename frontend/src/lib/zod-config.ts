import { z } from "zod";

// zod compiles parsers with `new Function` (and probes for it when schemas are created), which
// Trusted Types forbid. Must be imported before any module that defines a schema.
z.config({ jitless: true });
