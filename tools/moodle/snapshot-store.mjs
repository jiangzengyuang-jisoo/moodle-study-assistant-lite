import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { atomicJSON } from './core.mjs';

// The spool is written first. Python drains it only after committing every observation.
export function storeSnapshot(root, result) {
  const system = join(root, 'Study/_System');
  mkdirSync(join(system, 'collections'), {recursive: true});
  atomicJSON(join(system, 'collections', Date.now() + '-' + randomUUID() + '.json'), result);
  atomicJSON(join(system, 'refresh-latest.json'), result);
  if (result.collection_complete) atomicJSON(join(system, 'refresh-last-complete.json'), result);
}
