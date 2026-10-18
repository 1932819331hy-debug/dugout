# Squad needs: played positions vs listed positions

Generated 2026-10-18T16:48:08+00:00 by `uv run dugout-models backtest needs` (dugout_models/needs_backtest.py).

**What changed.** A squad's depth at each position group used to count every player once, at his listed Transfermarkt position. It now counts him where he actually starts (transfermarkt-datasets starting XIs since 2023-24): in every group with 25%+ of his starts, weighted by his share there. Players with fewer than 10 recorded starts (new signings from leagues the dataset lacks, youngsters) stay at their listed position. The six comparison squads are grouped the same way.

**No ground truth.** A need is a judgement, not an event, so this report shows the effect: the top two needs per Premier League club with each grouping, and a sanity check against what clubs did next.

## Top-two needs as the site shows them today (11 of 20 clubs change)

| Club | Listed positions (before) | Played positions (after) | Changed |
|---|---|---|---|
| arsenal | defensive midfield · goalkeeper | centre-forward · goalkeeper | yes |
| aston-villa | centre-back · central midfield | centre-back · central midfield |  |
| bournemouth | defensive midfield · goalkeeper | centre-back · goalkeeper | yes |
| brentford | defensive midfield · centre-back | defensive midfield · centre-back |  |
| brighton-hove-albion | central midfield · defensive midfield | central midfield · centre-forward | yes |
| chelsea | goalkeeper · central midfield | central midfield · goalkeeper | yes |
| coventry-city | defensive midfield · goalkeeper | defensive midfield · goalkeeper |  |
| crystal-palace | central midfield · full-back | full-back · central midfield | yes |
| everton | centre-back · goalkeeper | centre-back · goalkeeper |  |
| fulham | goalkeeper · winger | goalkeeper · defensive midfield | yes |
| hull-city | full-back · defensive midfield | full-back · centre-back | yes |
| ipswich-town | goalkeeper · defensive midfield | goalkeeper · centre-forward | yes |
| leeds-united | central midfield · centre-forward | central midfield · full-back | yes |
| liverpool | full-back · defensive midfield | full-back · defensive midfield |  |
| manchester-city | defensive midfield · goalkeeper | goalkeeper · defensive midfield | yes |
| manchester-united | full-back · centre-back | full-back · centre-back |  |
| newcastle-united | goalkeeper · centre-back | goalkeeper · centre-back |  |
| nottingham-forest | goalkeeper · defensive midfield | goalkeeper · defensive midfield |  |
| sunderland | defensive midfield · centre-back | full-back · defensive midfield | yes |
| tottenham-hotspur | goalkeeper · full-back | goalkeeper · full-back |  |

## Check against the summer 2026 window (14 of 20 clubs change on 1 June)

Needs as of 2026-06-01 (squads rebuilt to that day, see the module docstring), signings from Wikipedia's transfer lists from 2026-06-01 to 2026-09-15 (permanent, loan and free moves; 163 signings with a known position, 8 without one left out). "Hit" = the club signed at least one player in one of its two needs. A signing's groups are counted where he starts (25%+ of starts) and, separately, at his listed position. Random = two of the seven groups picked at random, given how many groups each club bought in.

| Signing's group counted by | Clubs | Listed-position needs (before) | Played-position needs (after) | Random two groups |
|---|---|---|---|---|
| played positions | 20 | 90% | 95% | 92% |
| listed positions | 20 | 90% | 90% | 89% |

| Club | June needs, before | June needs, after | Signed (groups where he starts) | Hit before | Hit after |
|---|---|---|---|---|---|
| arsenal | centre-back · defensive midfield | centre-forward · defensive midfield | Bruno Guimarães (central midfield, defensive midfield); Christos Tzolis (winger); Ezri Konsa (centre-back); Illan Meslier (goalkeeper); Piero Hincapié (centre-back, full-back) | yes | yes |
| aston-villa | goalkeeper · winger | goalkeeper · central midfield | Aaron Wan-Bissaka (full-back, winger); Alejandro Garnacho (winger); Ibrahim Mbaye (winger); Johan Manzambi (central midfield); João Gomes (central midfield, defensive midfield); Leon Goretzka (central midfield); Matteo Ruggeri (full-back, winger); Modou Kéba Cissé (centre-back); Nicolas Jackson (centre-forward); Taylor Harwood-Bellis (centre-back); Zion Suzuki (goalkeeper) | yes | yes |
| bournemouth | defensive midfield · centre-back | centre-back · defensive midfield | António Silva (centre-back); Michele Di Gregorio (goalkeeper); Álvaro Rodríguez (centre-forward) | yes | yes |
| brentford | defensive midfield · centre-back | defensive midfield · centre-back | Callum Wilson (centre-forward); El Hadji Malick Diouf (full-back, winger); Jaidon Anthony (winger); Jannik Schuster (centre-back); Mamadou Sangaré (central midfield) | yes | yes |
| brighton-hove-albion | centre-forward · central midfield | centre-forward · central midfield | Chema Andrés (defensive midfield); Costinha (full-back, winger); Jaouen Hadjam (full-back); Luka Vušković (centre-back); Matías Orozco (defensive midfield); Michael Svoboda (centre-back); Pascal Struijk (centre-back); Promise David (centre-forward); Zadok Yohanna (winger) | yes | yes |
| chelsea | goalkeeper · centre-back | goalkeeper · centre-back | Danny Welbeck (centre-forward); Dastan Satpayev (centre-forward, winger); Emiliano Martínez (goalkeeper); Emmanuel Emegha (centre-forward); Geovany Quenda (winger); Honest Ahanor (centre-back); Jordan Henderson (defensive midfield); Marco Palestra (winger); Maxence Lacroix (centre-back); Morgan Rogers (central midfield, winger); Pep Chavarría (full-back); Valentín Barco (central midfield) | yes | yes |
| coventry-city | goalkeeper · defensive midfield | goalkeeper · winger | Aurèle Amenda (centre-back); Caleb Yirenkyi (central midfield, defensive midfield); Carl Rushworth (goalkeeper); Dan Bentley (goalkeeper); Ethan Pinnock (centre-back); Frank Onyeka (central midfield, defensive midfield); Gustavo Hamer (central midfield); Loum Tchaouna (centre-forward, winger); Sidiki Cherif (centre-forward); Stephen Mfuni (centre-back); Taiwo Awoniyi (centre-forward); Yann Gboho (winger) | yes | yes |
| crystal-palace | central midfield · winger | central midfield · full-back | Anan Khalaili (winger); Axel Disasi (centre-back); Ben Chilwell (full-back, winger); Darío Osorio (winger); Dwight McNeil (winger); Evann Guessand (centre-forward, winger); Honest Ahanor (centre-back); Quinten Timber (central midfield); Takehiro Tomiyasu (full-back); Zavier Gozo (winger); Óscar Mingueza (full-back, winger) | yes | yes |
| everton | centre-back · goalkeeper | goalkeeper · centre-back | Ainsley Maitland-Niles (full-back); Brennan Johnson (winger); Christian Nørgaard (defensive midfield); Jack Grealish (winger); Merlin Röhl (central midfield, winger); Tyrique George (centre-forward, winger) | no | no |
| fulham | goalkeeper · centre-forward | goalkeeper · centre-forward | César Palacios (central midfield); David Affengruber (centre-back); Gonzalo García (centre-forward); Hugo Larsson (central midfield, defensive midfield); Jonah Kusi-Asare (centre-forward); Manuel Ángel (central midfield); Shea Charles (defensive midfield) | yes | yes |
| hull-city | defensive midfield · full-back | full-back · centre-back | Brooke Norton-Cuffy (full-back, winger); Christos Mouzakitis (central midfield); Elliot Stroud (winger); Hidemasa Morita (central midfield, defensive midfield); Ilyas Ansah (central midfield, centre-forward, winger); Jack Butland (goalkeeper); Jens Hjertø-Dahl (central midfield); Joe Gelhardt (centre-forward); Konstantinos Tzolakis (goalkeeper); Lucas Gourna-Douath (defensive midfield); Lucas Herrington (centre-back); Matt Targett (full-back); Mohamed-Ali Cho (centre-forward, winger); Nobel Mendy (centre-back); Robinio Vaz (centre-forward); Sorba Thomas (winger); Tim Iroegbunam (central midfield, defensive midfield) | yes | yes |
| ipswich-town | defensive midfield · centre-back | defensive midfield · centre-back | Abdoul Ouattara (full-back, winger); Abdul Fatawu (winger); Chuba Akpom (centre-forward, winger); Cédric Kipré (centre-back); Daizen Maeda (winger); Emersonn (centre-forward); Exequiel Palacios (central midfield, defensive midfield); Florentino Luís (defensive midfield); Issa Diop (centre-back); Julio Enciso (central midfield); Kayne van Oevelen (goalkeeper); Kjell Scherpen (goalkeeper); Saša Lukić (central midfield, defensive midfield); Zian Flemming (centre-forward) | yes | yes |
| leeds-united | goalkeeper · winger | goalkeeper · full-back | Harry Wilson (winger); James Trafford (goalkeeper); Jean-Mattéo Bahoya (winger); Melvin Bard (full-back, winger); Michael Zetterer (goalkeeper); Nico Elvedi (centre-back); Tarik Muharemović (centre-back) | yes | yes |
| liverpool | centre-back · defensive midfield | centre-back · full-back | Bradley Barcola (winger); Jérémy Jacquet (centre-back); Lucca Brughmans (goalkeeper); Ronald Araújo (centre-back); Víctor Muñoz (winger) | yes | yes |
| manchester-city | central midfield · defensive midfield | defensive midfield · central midfield | Allan (winger); Ayyoub Bouaddi (central midfield); Elliot Anderson (central midfield, defensive midfield); Enzo Fernández (central midfield); Gerónimo Rulli (goalkeeper); Iliman Ndiaye (winger); Jeremy Monga (winger); Pierce Charles (goalkeeper) | yes | yes |
| manchester-united | defensive midfield · central midfield | full-back · defensive midfield | Andrey Santos (central midfield, defensive midfield); Carlos Baleba (defensive midfield); Karl Darlow (goalkeeper); Tynan Thompson (winger); Youri Tielemans (central midfield, defensive midfield) | yes | yes |
| newcastle-united | goalkeeper · centre-back | goalkeeper · centre-back | Aladji Bamba (defensive midfield); Amar Dedić (full-back); Bazoumana Touré (winger); Lukáš Horníček (goalkeeper); Matias Fernandez-Pardo (centre-forward, winger); Nico González (central midfield, defensive midfield); Sean Steur (central midfield) | yes | yes |
| nottingham-forest | goalkeeper · defensive midfield | goalkeeper · centre-forward | Daniel Muñoz (full-back, winger); Liam Delap (centre-forward); Ousmane Diomande (centre-back); Xaver Schlager (central midfield) | no | yes |
| sunderland | defensive midfield · centre-back | defensive midfield · full-back | Dayann Methalie (winger); Jules Ahoka (defensive midfield); Kevin Danso (centre-back); Malick Fofana (winger); Thomas Meunier (full-back) | yes | yes |
| tottenham-hotspur | centre-forward · full-back | defensive midfield · full-back | Andy Robertson (full-back); Jan Paul van Hecke (centre-back); Marcos Senesi (centre-back); Martin Dúbravka (goalkeeper); Mateus Fernandes (central midfield); Mykhailo Mudryk (winger); Omar Marmoush (centre-forward); Sandro Tonali (central midfield, defensive midfield); Sávio (winger); Tosin Adarabioyo (centre-back) | yes | yes |
