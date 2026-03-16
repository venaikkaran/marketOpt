At a very base level, what we want is a human in the loop bayesian optimization engine. The human in the loop bayesian optimizer sees the state, provides the human with some options, the human considers it and enters it, and we get the next state of which we are trying to maximise something. Since there is a lot of data on the website, we need to have a data management strategy and pipeline in place that we want to test and make ready to ensure we don't make mistakes. Simply put, 
1) We want to reliably scrape the State for each year i.e., the info under company, market, consumer strategy tabs for each year. We then parse and clean it up and take either all data or some subset to put into our optimization algorithm. This is currently working decently well.
2) Then, we must suggest some decisions - these are under the "decisions" tab. Here is where the problem lies - we do NOT have a method to do this currently, and I want you to use the chrome devtools mcp to explore the decisions submenus and click through all things in the decisions submenu EXCEPT FOR ADVANCE, REPLAY, OR RESTART. Then, list out all decisions possible for Year0 and Year1. Ensure you use numbers for numerical fields, binary for radio fields, and discrete integers where there are options that are non-numerical/quanitfiable (for example, choosing a brand to partner with). Then, write code where a suggestion file can be taken in and applied on the webpage for the user to confirm themselves. 
3) Ensure you use delays to behave like a human.
4) You have the ability to play with the website yourself, if need be, using the Chrome Devtools mcp server/skill/plugin - simply use this mcp server/skill/plugin/tool and follow the steps. However, be EXTREMELY CAREFUL - DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY. DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY.
   1) Go to www.interpretive.com/students
   2) User Name: utda53727123
   3) Password: CleverGoal2
   4) Click Login
   5) Go to "Simulation" tab and click "Launch Benchmark Simulation" -> this will open a new window with the actual simulation engine. 
   6) On the absolute top are Start, Year 1 and 2. Year 2 may be currently greyed out which means we cant inspect it. You can select the year to review the data. The tab/menus (Company, Market, Consumer Survey) reflect the "state" of that year that we must assess and make decisions based on. Thus, if you select "Start" (year0), and navigate through Company/Market/Consumer Survey, you will see year0/state0. The decisions tab is where the user will make the choices i.e., decision0. So "Start"/year0 decisions tab is the decisions0. 
   7) The "decisions" tab for a given year are the decisions made during that year given that years state, to influence the state of next year. YearN reports reflect the outcome of Decision(N-1), not DecisionN. DecisionN is made while viewing YearN and produces YearN+1. For the general case of Year0 -> Decision0 -> Year1 -> Decision1 -> Year2, when the scraper is on the start page/Year0, the information under company, market, and consumer survey is for year0. The decisions under the decisions tab is ALSO for year0. When the person manually runs these through the sim, we get the results in Year1 and the opportunity in the next round of decisions to be made in year1 (decisions1) to me made to influence year2. Study each and every file in this repo or mention and analysis and update this discrepancy.
   8) Be EXTREMELY CAREFUL - DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY. DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY.

******************************************************************************************
We are trying to optimize a fictional simulated company named Allround in a simulator environment called PharmSim. We are treating as a black box optimization problem. At a high-level, we have three types of variables/settings –
1)      Inputs/Decisions – Knobs that we have control over that change the outcome of our company,
2)      Outputs/States – Values resultant from the simulation that we are “evaluated” on or are trying to ultimately optimize either alone, or as part of a multi objective cost function.
3)      Observations/States – These are other “variables” that we cannot directly change but can influence. These state variables may or may not have an effect on the outputs. These are observations that a human may use to evaluate their turn, and redo inputs to gain better outputs.

In PharmaSim, a given year can be considered to have a “state” – this state contains things like customer sentiment, profit/loss, revenue, etc. It is NOT necessary to optimize for all – for example, we do not have to optimize for customer sentiment, if it does not translate into maximized profits. However, an optimization method MAY find that optimizing for customer sentiment may optimize total profit loss.
So, we go from year0 (state0) make decisions (decision0) to produce state1/year1. We want to maximize profit/loss (whatever).

Additionally, the simulation is EXTREMELY expensive – we only have 25 tries to ensure our optimization maximises over this chain. The tests are deterministic i.e., for a given state, a specific input gives specific output. Additionally, give us a way to figure out the knobs that give the biggest change in the output i.e., turning what input knobs cause large changes in outputs. Sometimes, combinations of input knobs may need to be turned in conjunction to cause required results in the output. How can we A) get the optimal value, and B) get the relations?


Be EXTREMELY CAREFUL - DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY. DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY.
Test out the following using the Chrome webtools skill and mcp server yourself - 
1) Total Budget Constraint (spending ≤ available budget) - while conceptually correct, is this actually true on the simulator i.e., does it raise an error? Set values on the website and test it out. 
2) Tell me what page has the msg_comparison_target - I dont know what this is
3) What page has Ad Agency Fee Interaction with Ad Budget?
4) What page has Sales Force Allocation vs. Channel Presence
5) Symptom/Demographic Targeting: "None Checked = All Targeted" - Use a subagent to fix this in the code. 
6) Benefit Promotion vs. Formulation Consistency - this is correct. Use a subagent to fix this in the code. 
7) tell me what page Promotional Allowance Uniformity Consideration is - I dont know what this is 
Be EXTREMELY CAREFUL - DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY. DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY.

Additionally, when values are applied to the simulator and then we click the blue "SAVE" button, it does some calculations of sorts or something to raise flags and provide errors. Can you to "cut out the middleman" so to speak and just find these calculations as present in the website?

1) Even though not an actual hard limit, I want you to enforce the Total Budget Constraint


***********************
We are trying to optimize a fictional simulated company named Allround in a simulator environment called PharmSim. We are treating as a black box optimization problem. At a high-level, we have two types of variables/settings –
1) Inputs/Decisions – Knobs that we have control over that change the outcome of our company,
2) Outputs/States – Values resultant from the simulation that we are “evaluated” on or are trying to ultimately optimize either alone, or as part of a multi objective cost function.

In PharmaSim, a given year can be considered to have a “state” – this state contains things like customer sentiment, profit/loss, revenue, etc. We want to maximise the following function - 
(performance_summary.unit_sales * 3.5) + 
(income_statement.net_income * 4.5) + 
(income_statement.manufacturer_sales * 5) + 
(income_statement.manufacturer_sales/(income_statement.cost_of_goods_sold+income_statement.total_marketing+performance_summary.promotional_allowance+performance_summary.fixed_costs) * 6)

Based on the following parameters that are considered as the inputs - 
  Sales Force (8 fields) — integer [0, 1000]

  ┌──────────────────┬──────────────────────────────────┐
  │       Key        │           Description            │
  ├──────────────────┼──────────────────────────────────┤
  │ sf_independent   │ Independent Drugstores headcount │
  ├──────────────────┼──────────────────────────────────┤
  │ sf_chain         │ Chain Drugstores headcount       │
  ├──────────────────┼──────────────────────────────────┤
  │ sf_grocery       │ Grocery Stores headcount         │
  ├──────────────────┼──────────────────────────────────┤
  │ sf_convenience   │ Convenience Stores headcount     │
  ├──────────────────┼──────────────────────────────────┤
  │ sf_mass          │ Mass Merchandisers headcount     │
  ├──────────────────┼──────────────────────────────────┤
  │ sf_wholesaler    │ Wholesaler Support headcount     │
  ├──────────────────┼──────────────────────────────────┤
  │ sf_merchandisers │ Merchandisers headcount          │
  ├──────────────────┼──────────────────────────────────┤
  │ sf_detailers     │ Detailers headcount              │
  └──────────────────┴──────────────────────────────────┘

  Pricing (5 fields)

  ┌─────────────────────┬────────────┬────────────┬─────────────────────────────────────────┐
  │         Key         │    Type    │   Range    │               Description               │
  ├─────────────────────┼────────────┼────────────┼─────────────────────────────────────────┤
  │ msrp                │ continuous │ [$1, $50]  │ Manufacturer Suggested Retail Price     │
  ├─────────────────────┼────────────┼────────────┼─────────────────────────────────────────┤
  │ discount_under_250  │ continuous │ [10%, 50%] │ Volume discount for orders < 250 units  │
  ├─────────────────────┼────────────┼────────────┼─────────────────────────────────────────┤
  │ discount_under_2500 │ continuous │ [10%, 50%] │ Volume discount for orders < 2500 units │
  ├─────────────────────┼────────────┼────────────┼─────────────────────────────────────────┤
  │ discount_2500_plus  │ continuous │ [10%, 50%] │ Volume discount for orders 2500+ units  │
  ├─────────────────────┼────────────┼────────────┼─────────────────────────────────────────┤
  │ discount_wholesale  │ continuous │ [10%, 50%] │ Wholesale discount %                    │
  └─────────────────────┴────────────┴────────────┴─────────────────────────────────────────┘

  Ordering constraint: discount_under_250 ≤ discount_under_2500 ≤ discount_2500_plus ≤ discount_wholesale (server-enforced)

  Advertising (16 fields)

  ┌──────────────────────────────┬────────────┬───────────┬─────────────────────────────────────────────┐
  │             Key              │    Type    │   Range   │                 Description                 │
  ├──────────────────────────────┼────────────┼───────────┼─────────────────────────────────────────────┤
  │ ad_budget                    │ continuous │ [0, ∞)    │ Ad budget in $M (budget-limited)            │
  ├──────────────────────────────┼────────────┼───────────┼─────────────────────────────────────────────┤
  │ ad_agency                    │ discrete   │ {1, 2, 3} │ 1=Brewster(15%), 2=Sully(10%), 3=Lester(5%) │
  ├──────────────────────────────┼────────────┼───────────┼─────────────────────────────────────────────┤
  │ symptom_cold                 │ binary     │ T/F       │ Target cold sufferers                       │
  ├──────────────────────────────┼────────────┼───────────┼─────────────────────────────────────────────┤
  │ symptom_cough                │ binary     │ T/F       │ Target cough sufferers                      │
  ├──────────────────────────────┼────────────┼───────────┼─────────────────────────────────────────────┤
  │ symptom_allergy              │ binary     │ T/F       │ Target allergy sufferers                    │
  ├──────────────────────────────┼────────────┼───────────┼─────────────────────────────────────────────┤
  │ demo_young_singles           │ binary     │ T/F       │ Target Young Singles                        │
  ├──────────────────────────────┼────────────┼───────────┼─────────────────────────────────────────────┤
  │ demo_young_families          │ binary     │ T/F       │ Target Young Families                       │
  ├──────────────────────────────┼────────────┼───────────┼─────────────────────────────────────────────┤
  │ demo_mature_families         │ binary     │ T/F       │ Target Mature Families                      │
  ├──────────────────────────────┼────────────┼───────────┼─────────────────────────────────────────────┤
  │ demo_empty_nesters           │ binary     │ T/F       │ Target Empty Nesters                        │
  ├──────────────────────────────┼────────────┼───────────┼─────────────────────────────────────────────┤
  │ demo_retired                 │ binary     │ T/F       │ Target Retired                              │
  ├──────────────────────────────┼────────────┼───────────┼─────────────────────────────────────────────┤
  │ msg_primary_pct              │ continuous │ [0, 100]  │ Primary ad message %                        │
  ├──────────────────────────────┼────────────┼───────────┼─────────────────────────────────────────────┤
  │ msg_benefits_pct             │ continuous │ [0, 100]  │ Benefits ad message %                       │
  ├──────────────────────────────┼────────────┼───────────┼─────────────────────────────────────────────┤
  │ msg_comparison_pct           │ continuous │ [0, 100]  │ Comparison ad message %                     │
  ├──────────────────────────────┼────────────┼───────────┼─────────────────────────────────────────────┤
  │ msg_reminder_pct             │ continuous │ [0, 100]  │ Reminder ad message %                       │
  ├──────────────────────────────┼────────────┼───────────┼─────────────────────────────────────────────┤
  │ msg_comparison_target        │ discrete   │ {2..11}   │ Comparison target brand ID                  │
  ├──────────────────────────────┼────────────┼───────────┼─────────────────────────────────────────────┤
  │ (9 benefit checkboxes below) │            │           │                                             │
  └──────────────────────────────┴────────────┴───────────┴─────────────────────────────────────────────┘

  Sum constraint: msg_primary_pct + msg_benefits_pct + msg_comparison_pct + msg_reminder_pct = 100 (server-enforced)

  Benefit Claims (9 fields) — all binary

  ┌────────────────────────────────┬───────────────────────────┐
  │              Key               │        Description        │
  ├────────────────────────────────┼───────────────────────────┤
  │ benefit_relieves_aches         │ Relieves Aches            │
  ├────────────────────────────────┼───────────────────────────┤
  │ benefit_clears_nasal           │ Clears Nasal Congestion   │
  ├────────────────────────────────┼───────────────────────────┤
  │ benefit_reduces_chest          │ Reduces Chest Congestion  │
  ├────────────────────────────────┼───────────────────────────┤
  │ benefit_dries_runny_nose       │ Dries Up Runny Nose       │
  ├────────────────────────────────┼───────────────────────────┤
  │ benefit_suppresses_coughing    │ Suppresses Coughing       │
  ├────────────────────────────────┼───────────────────────────┤
  │ benefit_relieves_allergies     │ Relieves Allergy Symptoms │
  ├────────────────────────────────┼───────────────────────────┤
  │ benefit_minimizes_side_effects │ Minimizes Side Effects    │
  ├────────────────────────────────┼───────────────────────────┤
  │ benefit_wont_cause_drowsiness  │ Won't Cause Drowsiness    │
  ├────────────────────────────────┼───────────────────────────┤
  │ benefit_helps_you_rest         │ Helps You Rest            │
  └────────────────────────────────┴───────────────────────────┘

  Promotion (15 fields)

  ┌───────────────────────┬────────────┬────────────┬─────────────────────────────────────┐
  │          Key          │    Type    │   Range    │             Description             │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ allowance_independent │ continuous │ [10%, 20%] │ Promo allowance — Independent       │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ allowance_chain       │ continuous │ [10%, 20%] │ Promo allowance — Chain             │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ allowance_grocery     │ continuous │ [10%, 20%] │ Promo allowance — Grocery           │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ allowance_convenience │ continuous │ [10%, 20%] │ Promo allowance — Convenience       │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ allowance_mass        │ continuous │ [10%, 20%] │ Promo allowance — Mass Merch        │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ allowance_wholesale   │ continuous │ [10%, 20%] │ Promo allowance — Wholesale         │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ coop_ad_budget        │ continuous │ [0, ∞)     │ Co-op ad budget ($M)                │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ coop_ad_independent   │ binary     │ T/F        │ Co-op ads — Independent             │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ coop_ad_chain         │ binary     │ T/F        │ Co-op ads — Chain                   │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ coop_ad_grocery       │ binary     │ T/F        │ Co-op ads — Grocery                 │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ coop_ad_convenience   │ binary     │ T/F        │ Co-op ads — Convenience             │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ coop_ad_mass          │ binary     │ T/F        │ Co-op ads — Mass Merch              │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ pop_budget            │ continuous │ [0, ∞)     │ POP display budget ($M)             │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ pop_independent       │ binary     │ T/F        │ POP — Independent                   │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ pop_chain             │ binary     │ T/F        │ POP — Chain                         │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ pop_grocery           │ binary     │ T/F        │ POP — Grocery                       │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ pop_convenience       │ binary     │ T/F        │ POP — Convenience                   │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ pop_mass              │ binary     │ T/F        │ POP — Mass Merch                    │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ trial_budget          │ continuous │ [0, ∞)     │ Trial size budget ($M)              │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ coupon_budget         │ continuous │ [0, ∞)     │ Coupon budget ($M)                  │
  ├───────────────────────┼────────────┼────────────┼─────────────────────────────────────┤
  │ coupon_amount         │ discrete   │ {0,1,2,3}  │ Face value: $0.25/$0.50/$0.75/$1.00 │


Given the extremely large and varied search space, we are trying to make a human in the loop simulator that optimizes quickly. Additionally, the simulation is EXTREMELY expensive – we only have 25 tries to ensure our optimization maximises over this chain. The tests are deterministic i.e., for a given state, a specific input gives specific output. Additionally, give us a way to figure out the knobs that give the biggest change in the output i.e., turning what input knobs cause large changes in outputs. Sometimes, combinations of input knobs may need to be turned in conjunction to cause required results in the output. How can we A) get the optimal value, and B) get the relations? Given all this information, I want you to suggest and optimize an optimization strategy into which I can add constraints (like summing constraints, less than greater than constrains and any other) and a strategy to extract information and links. 

Some clarification and consolidation may be required - for any phase, the decisions may or may NOT be fully populated:
1) The state 