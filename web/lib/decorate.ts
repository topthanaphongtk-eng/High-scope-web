import type { Capture } from "./types";
import { toImageUrl } from "./format";

export function decorate(c: Capture): Capture {
  for (const f of c.files) {
    f.image_rel = toImageUrl(f.fused_path);
  }
  return c;
}
