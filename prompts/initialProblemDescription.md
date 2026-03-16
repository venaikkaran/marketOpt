I am trying to write an optimization framework for the PharmaSim simulator. 
At a high-level, the simulator is a stateful system - currently, there are three total states, and 2 decisions. So, we have financial results for "Start"/Year0, Year1, and Year2. Then, we have Decisions1 and Decisions2. Ultimately we want to write an optimizer that uses as few iterations as possible to optimize for some metrics. Sometimes, we can only run an evaluation run from Year1 -> Decision2 -> Year2. Other times, we can run the whole routine i.e., Year0 -> Decision1 -> Year1 -> Decision2 -> Year2.

Given this high level idea, we need to figure out the data management strategy to feed the optimization engine since there are a huge number of variables. We have CSVs of all the states/years. We want to also figure out the decisions and how they fit into our data. We also need clean run separation i.e., data from different runs should be in different folders. Then, we need to parse the excel data and clean it up i.e., parse and format it such that our optimization loop can use it in the future. 

I want you to study the @src/parser.py and @src/scraper.py and suggest how we can get total integration and a whole data pipeline that can be later used for optimization. 

Use upto 250 parallel subagents to understand the codebase and discuss/suggest.

The key part before I start playing around with things is the data management. 

*********************************************************************
We are developing an optimization framework for the PharmaSim simulator. 

At a high-level, the simulator is a stateful system - currently, there are three total states, and 2 decisions. So, we have financial results for "Start"/Year0, Year1, and Year2. Then, we have Decisions0 and Decisions1. Ultimately we want to write an optimizer that uses as few iterations as possible to optimize for some metrics. 

We have two ways of running Simulation in the webapp. Consider the following naming convention - we have Y0 -> D0 -> Y1 -> D1 -> Y2 , where Yn are the years (states), and Dm are the decisions we pick. 
**Advance** - After selecting some simulation results at the current state, we want to lock in those and run tests. Running the tests is EXTREMELY EXPENSIVE - NEVER CLICK ON OR OTHERWISE ACCEPT OR MOVE ON WITH ADVANCE. 
**Replay** - Keep Y0 -> D0 -> Y1 LOCKED. Only retry D1 -> Y2. We have LIMITED replays. STRICTLY DO NOT CLICK **REPLAY** on your own or interact with it in any way, shape or form. This reverts back the run and is evaluation expensive. 
**Restart** - From scratch, do Y0 -> D0 -> Y1 -> D1 -> Y2 . We have LIMITED restarts. STRICTLY DO NOT CLICK **RESTART** on your own or interact with it in any way, shape or form. This reverts back the run and is evaluation expensive. 

This means that sometimes, we can only run an evaluation from Year1 -> Decision1 -> Year2. Other times, we can run the whole routine i.e., Year0 -> Decision0 -> Year1 -> Decision1 -> Year2.

Given this, I am trying to understand how exactly I should approach the data scraping and testing pattern. Basically, I will likely use a bayesian style optimization. My confusion/questions/discussion is mainly on the side of how would I organize the data and run bayesian optimization for it. Simulations are expensive and I can run two types:
1) Full Decision Chain - Y0 -> D0 -> Y1 -> D1 -> Y2 (**RESTART** - DO NOT TOUCH YOURSELF)
2) Half Decision Chain - Y1 -> D1 -> Y2 (**REPLAY** - DO NOT TOUCH YOURSELF)
We are trying to optimise some metrics in Y2. However Y2 is obviously dependent on D1 and Y1, which are based on Y0 and D0. I have significantly more compute budget for the half decision chain (Y1 -> D1 -> Y2) than I do for full decision chain (Y0 -> D0 -> Y1 -> D1 -> Y2). Thus, it would be prudent to learn the system a little bit more through the half decision tree, and then when we are confident, learn over full decision tree. 

Once we retry or restart, the data from previous runs becomes unavailable. Also we have a very LIMITED retry and restart budget (making each check very expensive). The other problem is that scraping and setting up data is very cumbersome - We have to fill it in each time. I do NOT want to automate the process since there may be tonnes of errors. So basically, I want a human in the loop bayesian optimizer where the optimizer will provide the next best guess, the human can apply their brain and check what is being done, the human then clicks the **Advance** button, and moves forward, and the bayesian model gets updated with the selection that the human made. 

How would you suggest we do this/achieve this from the actual glue logic, implementation, and most importantly "Human in the loop" perspective. Use upto 200 parallel subagents to study and understand the code and also the data files at hand. You can also use the Chrome Web MCP (skills, mcp server, and plugin) to interact with the website - Be EXTREMELY CAREFUL - DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY. DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY.

******************************
You have the ability to play with the website yourself, if need be, using the Chrome Devtools mcp server/skill/plugin - simply use this mcp server/skill/plugin/tool and follow the steps. However, be EXTREMELY CAREFUL - DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY. DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY.
1) Go to www.interpretive.com/students
2) User Name: utda53727123
3) Password: CleverGoal2
4) Click Login
5) Go to "Simulation" tab and click "Launch Benchmark Simulation" -> this will open a new window with the actual simulation engine. 
6) On the absolute top are Start, Year 1 and 2. Year 2 may be currently greyed out which means we cant inspect it. You can select the year to review the data. The tab/menus (Company, Market, Consumer Survey) reflect the "state" of that year that we must assess and make decisions based on. Thus, if you select "Start" (year0), and navigate through Company/Market/Consumer Survey, you will see year0/state0. The decisions tab is where the user will make the choices i.e., decision0. So "Start"/year0 decisions tab is the decisions0. 
7) The "decisions" tab for a given year are the decisions made during that year given that years state, to influence the state of next year. YearN reports reflect the outcome of Decision(N-1), not DecisionN. DecisionN is made while viewing YearN and produces YearN+1. For the general case of Year0 -> Decision0 -> Year1 -> Decision1 -> Year2, when the scraper is on the start page/Year0, the information under company, market, and consumer survey is for year0. The decisions under the decisions tab is ALSO for year0. When the person manually runs these through the sim, we get the results in Year1 and the opportunity in the next round of decisions to be made in year1 (decisions1) to me made to influence year2. Study each and every file in this repo or mention and analysis and update this discrepancy.
8) Be EXTREMELY CAREFUL - DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY. DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY.

A) Hard constraints - go ahead and fix these and add comments in the code as to why.
B) Conditional Irrelevance - go ahead and fix these
C) Equivalence Dedup - Fix these
D) Formulation Benefit Consistency - Fix these. 
E) Budget Ceiling - Implement this but bound this to our yearly budgets from the scraped data i.e., dont just limit to a magci value of ~$44M
F) Recommended Reparametrization - do NOT change this. 
Use subagents to change the precise sections of the code. Then, use subagents to commit this to your memory. Lastly, use a new subagent to update the code with proper comments describing the details of some of these constraints. 
