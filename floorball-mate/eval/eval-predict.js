// Replays the recorded match from the OLC repo and measures how often the suggestion is right.
// usage: node eval/eval-predict.js [path/to/sample-data]
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { suggest } from '../js/predict.js';

const dir = process.argv[2] ?? new URL('../../sample-data/', import.meta.url).pathname.replace(/^\/(\w:)/, '$1');
const events = JSON.parse(readFileSync(join(dir, 'full-match-events.json'), 'utf8')).map((e) => e.body);
const formations = JSON.parse(readFileSync(join(dir, 'formations.json'), 'utf8'));
const key = (p) => [...p].sort((a, b) => a - b).join(',');

function run(useFormations) {
  const stats = {};
  for (const team of ['home', 'away']) {
    const subs = events.filter((e) => e.type === 'substitution' && e.team === team);
    subs.forEach((e, i) => {
      const prev = subs[i - 1];
      const current = prev && prev.period === e.period ? prev.players : null;
      const s = suggest({ history: subs.slice(0, i).map((x) => x.players), current, formations: useFormations ? formations[team] : [] });
      for (const g of [e.period, 'celkem']) {
        const st = (stats[g] ??= { n: 0, top1: 0, top3: 0 });
        st.n++;
        if (s[0] && key(s[0].players) === key(e.players)) st.top1++;
        if (s.some((x) => key(x.players) === key(e.players))) st.top3++;
      }
    });
  }
  return stats;
}

for (const [label, f] of [['s předvolbami řad', true], ['bez předvoleb (učení jen z historie)', false]]) {
  console.log(`\n${label}`);
  for (const [g, st] of Object.entries(run(f)))
    console.log(`  ${g === 'celkem' ? 'celkem  ' : g + '. část '}  n=${String(st.n).padStart(3)}  1. návrh přesně: ${Math.round((100 * st.top1) / st.n)} %   mezi 3 návrhy: ${Math.round((100 * st.top3) / st.n)} %`);
}
