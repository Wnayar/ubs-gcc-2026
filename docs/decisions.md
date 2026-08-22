# Decision & change log

One line per decision or requirement change, newest last. This doubles as the
"log changes" artifact for Product Owner check-ins — keep it current, it is scored.

| Time (SGT) | Phase | What changed / was decided | Why / who said so |
|---|---|---|---|
| 2026-08-21 | setup | Single FastAPI service on Render (Singapore region), one router per phase | one URL survives every phase, registered once with the controller |
| 2026-08-21 | 1 (practice) | POST /square takes {"value": n}, returns {"result": n²}; ints stay ints (5→25 not 25.0); replaced the throwaway sample /square (field `number`) | statement.pdf example output is `25` exactly; sample endpoint was only a deploy-pipeline check |
| 2026-08-21 | setup | Stay on Render free plan; warm up manually (curl /health) right before triggering each evaluation instead of a scheduled ping | team decision — keep it free; evaluations are user-triggered so we control timing |
| 2026-08-22 | 2 | POST /solve: base64 JSON in {"payload"} -> {"adaptOutput":{id,name,action,priority}}; lenient decode (std/url-safe/unpadded/plain JSON), priority LOW=1 MEDIUM=2 HIGH=3 (unknown -> 0), action lowercased, V1 name/id spellings bridged | statement gives one example and says the payload "somehow decodes"; the ambiguity is deliberate (source file is adapt-amb.md) so we guessed the ladder around the given HIGH=3 and never 500 |

