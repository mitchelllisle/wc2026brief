/**
 * WC2026 knockout bracket — shared simulation utilities.
 *
 * R32 encodes the official bracket draw order so adjacent pairs feed the same
 * R16 match, and that pattern cascades through every round.
 * Sources: wikipedia.org/wiki/2026_FIFA_World_Cup_knockout_stage
 */

// — R32 matchups in bracket-display order ——————————————————————————————
// Adjacent pairs (indices 0-1, 2-3, …) feed the same R16 slot.
// Updated to official WC2026 confirmed R32 draw.
export const R32 = [
  // — SF1 side —————————————————————————————————
  // R16 → QF (SF1 upper)
  ['South Africa',      'Canada'             ], // confirmed
  ['Netherlands',       'Morocco'            ], // confirmed
  // R16 → QF (SF1 upper)
  ['Germany',           'Paraguay'           ],
  ['France',            'Sweden'             ],
  // R16 → QF (SF1 lower)
  ['Belgium',           'Senegal'            ],
  ['United States',     'Bosnia-Herzegovina' ], // confirmed
  // R16 → QF (SF1 lower)
  ['Spain',             'Austria'            ],
  ['Portugal',          'Croatia'            ],
  // — SF2 side —————————————————————————————————
  // R16 → QF (SF2 upper)
  ['Brazil',            'Japan'              ], // confirmed
  ['Ivory Coast',       'Norway'             ],
  // R16 → QF (SF2 upper)
  ['Mexico',            'Ecuador'            ],
  ['England',           'Congo DR'           ],
  // R16 → QF (SF2 lower)
  ['Switzerland',       'Algeria'            ],
  ['Colombia',          'Ghana'              ],
  // R16 → QF (SF2 lower)
  ['Australia',         'Egypt'              ],
  ['Argentina',         'Cape Verde Islands' ],
];

/**
 * Simulate the full bracket given an array of team objects
 * (each with `name`, `title_probability`, and `fifa_rank`).
 * Returns { r32, r16, qf, sf, fin, champ } where each round is an array of
 * { a, b, w } match objects (w = predicted winner name).
 */
export function runBracket(teams) {
  const T = new Map(teams.map(t => [t.name, t]));

  function pick(a, b) {
    const sa = T.get(a)?.title_probability ?? 0;
    const sb = T.get(b)?.title_probability ?? 0;
    if (sa !== sb) return sa > sb ? a : b;
    return (T.get(a)?.fifa_rank ?? 999) <= (T.get(b)?.fifa_rank ?? 999) ? a : b;
  }

  function sim(pairs) {
    return pairs.map(([a, b]) => ({ a, b, w: pick(a, b) }));
  }

  function adv(res) {
    const p = [];
    for (let i = 0; i < res.length; i += 2) p.push([res[i].w, res[i + 1].w]);
    return sim(p);
  }

  const r32   = sim(R32);
  const r16   = adv(r32);
  const qf    = adv(r16);
  const sf    = adv(qf);
  const fin   = adv(sf);
  const champ = fin[0].w;

  return { r32, r16, qf, sf, fin, champ };
}

/**
 * Given a completed bracket result, return a Map<teamName, depth> where:
 *   0 = exits R32  (no knockout rounds won)
 *   1 = exits R16  (won R32)
 *   2 = exits QF   (won R16)
 *   3 = exits SF   (won QF)
 *   4 = finalist   (won SF, loses final)
 *   5 = champion   (won final)
 *
 * Having multiple teams at high depths compounds a manager's advantage.
 */
export function computeTeamDepths({ r32, r16, qf, sf, fin, champ }) {
  const rounds = [r32, r16, qf, sf, fin];
  const depths = new Map();
  for (let i = 0; i < rounds.length; i++) {
    for (const m of rounds[i]) {
      for (const t of [m.a, m.b]) {
        depths.set(t, Math.max(depths.get(t) ?? 0, i));
      }
    }
  }
  if (champ) depths.set(champ, 5);
  return depths;
}
