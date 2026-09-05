# Question pool — Insurance Claims RAG

Written before any trace was read. Its only job is to **generate the trace
corpus**; the graded sample of 20 is drawn at random from `traces.jsonl`, not
from this list.

Format: `ID | KIND | question`

Kinds: **A** single-endorsement lookup · **B** base policy vs endorsement ·
**C** cross-document / multi-hop · **D** procedural (FNOL, authority, subrogation) ·
**E** out of scope · **F** vague / underspecified · **G** policyholder phrasing

Some questions deliberately carry claimant names, claim numbers and policy
numbers, so the redaction path is exercised on real input rather than assumed.

## A — single endorsement lookup

Q001 | A | Under endorsement HO-2026-01, what is the limit of liability for water backup and sump discharge?
Q002 | A | What deductible applies to a water backup claim under HO-2026-01?
Q003 | A | Under HO-2026-02, exactly where does service line coverage begin and end?
Q004 | A | What are the covered causes of loss under the service line endorsement HO-2026-02?
Q005 | A | Under HO-2026-03, what settlement basis applies to covered equipment that is ten years or older?
Q006 | A | What equipment is specifically NOT covered under the home equipment breakdown endorsement?
Q007 | A | Under HO-2026-04, what is the deductible for scheduled personal property?
Q008 | A | Which classes of property can be scheduled under HO-2026-04?
Q009 | A | Under HO-2026-05, what costs are excluded from increased ordinance or law coverage?
Q010 | A | What is the time limit for ordinance or law costs under HO-2026-05?
Q011 | A | Under HO-2026-06, what qualifies as a home business?
Q012 | A | What business liability limit applies under Part 2 of HO-2026-06?
Q013 | A | Under HO-2026-07, what is the deductible for an identity fraud claim?
Q014 | A | What are the exclusions specific to the identity fraud endorsement HO-2026-07?
Q015 | A | Under HO-2026-08, what is the depreciation schedule for roof surfacing?
Q016 | A | How does HO-2026-08 treat cosmetic damage to a roof?
Q017 | A | When may endorsement HO-2026-08 not be applied?
Q018 | A | What is the definition of breakdown under HO-2026-03?
Q019 | A | What conditions must be met for water backup coverage to apply under HO-2026-01?
Q020 | A | What is the blanket versus itemised distinction under HO-2026-04?

## B — base policy vs endorsement

Q021 | B | What deductible applies to a water backup claim on a policy with the base HO-3 and HO-2026-01?
Q022 | B | Does the water backup deductible stack with the base all-perils deductible?
Q023 | B | The base HO-3 settles contents at actual cash value. What changes when HO-2026-04 is attached?
Q024 | B | How does the windstorm deductible in the base form interact with HO-2026-08?
Q025 | B | Is business property covered under the base HO-3 without HO-2026-06 attached?
Q026 | B | Does the base policy cover ordinance or law costs at all, or only with HO-2026-05?
Q027 | B | A claim involves both a base-form water damage exclusion and HO-2026-01. Which controls?
Q028 | B | What is the Coverage C limit under the base form, and does HO-2026-04 raise it?
Q029 | B | Does service line damage fall under the base form's underground utility exclusion?
Q030 | B | Which endorsement overrides the base form's roof settlement basis, and how?
Q031 | B | Is loss of use payable on a water backup claim, under the base form or the endorsement?
Q032 | B | Does the base HO-3 exclusion for mechanical breakdown survive when HO-2026-03 is attached?
Q033 | B | What jewellery sublimit applies under the base form, and what changes if items are scheduled?
Q034 | B | Are the base form Duties After Loss still required for an identity fraud claim?

## C — cross-document / multi-hop

Q035 | C | A water backup claim needs emergency water extraction. What authority does the adjuster have, and does HO-2026-01 cover the mitigation cost?
Q036 | C | A service line failure was caused by a contractor. What does the subrogation procedure require, and does HO-2026-02 affect recovery?
Q037 | C | For a $9,000 equipment breakdown claim, is the adjuster authorised to settle it, and what settlement basis applies?
Q038 | C | A roof claim under HO-2026-08 will be denied in part. What does CP-09 require before issuing the denial?
Q039 | C | An identity fraud claim comes in through the web portal. What FNOL data is mandatory, and what deductible applies?
Q040 | C | A home-sharing guest is injured. Which severity tier is this at FNOL, and does HO-2026-06 Part 3 respond?
Q041 | C | A scheduled ring is lost. What reserving does CP-09 require and what deductible applies under HO-2026-04?
Q042 | C | A basement flooded and the freezer failed. Which two endorsements respond, and do both deductibles apply?
Q043 | C | Ordinance or law costs push a rebuild over the adjuster's authority limit. What happens next?
Q044 | C | Can a reservation of rights letter be issued on a water backup claim while coverage is being confirmed?
Q045 | C | Two claims are filed for the same water backup event. What does the duplicate handling rule say, and does the limit reinstate?
Q046 | C | A roof claim is reopened after twelve months. Does the ACV schedule still apply and what does the reopen rule require?
Q047 | C | What is the response target for a severity tier 1 loss, and which endorsements most commonly produce tier 1 losses?
Q048 | C | A home business laptop is stolen in a burglary. Which document sets the limit and which sets the deductible?

## D — procedural

Q049 | D | What are the settlement authority limits for an adjuster under CP-09?
Q050 | D | What reserving is required when coverage is still under investigation?
Q051 | D | How is the deductible applied when two coverages are involved in one loss?
Q052 | D | What must be documented before a claim is denied?
Q053 | D | When is a reservation of rights letter required?
Q054 | D | What are the salvage and subrogation obligations under CP-09?
Q055 | D | What are the file audit standards for a closed claim?
Q056 | D | What intake channels are available for first notice of loss?
Q057 | D | What FNOL data is mandatory at intake?
Q058 | D | What are the severity tiers and the response target for each?
Q059 | D | What emergency mitigation authority exists before coverage is confirmed?
Q060 | D | How is coverage confirmation handled at FNOL?
Q061 | D | What is the reopen and duplicate handling rule?
Q062 | D | When must a claim be escalated, and to whom?
Q063 | D | Can the person taking the FNOL call confirm coverage to the policyholder?
Q064 | D | What does the subrogation procedure CP-12 require for a third-party recovery?

## E — out of scope

Q065 | E | What is the flood insurance deductible under the NFIP?
Q066 | E | How do I file a claim for my car after a collision?
Q067 | E | What is the earthquake coverage limit on this policy?
Q068 | E | What are the workers compensation rates in this state?
Q069 | E | Does this policy cover my boat stored at a marina?
Q070 | E | What is the commercial general liability limit for a contractor?
Q071 | E | How much life insurance should I buy?
Q072 | E | What is the 2027 edition of the HO-3 form going to change?
Q073 | E | Is my pet's veterinary bill covered?
Q074 | E | What is the surrender value of my annuity?

## F — vague / underspecified

Q075 | F | What is the deductible?
Q076 | F | Is this covered?
Q077 | F | How much will they pay for my roof?
Q078 | F | What is the limit on the endorsement?
Q079 | F | Does the exclusion apply here?
Q080 | F | What edition applies to my claim?
Q081 | F | Can I get more coverage?
Q082 | F | Why was my claim reduced?
Q083 | F | What are the deadlines?
Q084 | F | Which form covers this?

## G — policyholder phrasing (some with claimant identifiers)

Q085 | G | My basement flooded after heavy rain. Am I covered?
Q086 | G | The pipe from my house to the street broke. Who pays for digging up the yard?
Q087 | G | My air conditioner died last week. Is that a claim?
Q088 | G | My freezer failed and I lost all the food in it. What do I get back?
Q089 | G | How much jewellery is covered without listing it individually?
Q090 | G | Do I need an appraisal before you will cover my wedding ring?
Q091 | G | My roof was damaged by hail. Why is the cheque less than my contractor's estimate?
Q092 | G | My metal roof is dented but it is not leaking. Will you pay to replace it?
Q093 | G | Someone opened a credit card in my name. What does the policy do for me?
Q094 | G | I run a small business from home. Is my equipment covered if it is stolen?
Q095 | G | Claimant Maria Delgado, claim CLM-482911, policy HO-5591027: her basement backed up on 14 March. What deductible applies?
Q096 | G | Following up on claim CLM-513882 for Robert Chen — his air conditioner failed and he wants to know the settlement basis.
Q097 | G | Priya Raghavan (claim CLM-470335) rents her house out on a hosting site sometimes. Is a guest injury covered?
Q098 | G | Claim CLM-499710, claimant Daniel Okafor: hail damaged his ten-year-old asphalt roof. How much depreciation applies?
Q099 | G | Sandra Whitfield, policy HO-5610442, claim CLM-521004 — identity fraud reported through the call centre. What is her deductible?
Q100 | G | For claim CLM-488216 (claimant Thomas Bergeron), the freezer and the basement both flooded. Does he pay two deductibles?
