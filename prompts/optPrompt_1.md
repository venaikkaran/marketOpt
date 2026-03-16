We are now focusing on the development of a bayesian optimization routine. Since we have a tonne of knobs, we have manually selected a few. This will be called optimization routine year1 V2. In this, we will record the state of year1, then take the previous decisions of year1, suggest some values, apply those values, and see year2. We want to optimize for the following - 

Cost function = 
(income_statement.manufacturer_sales * 2/3) + 
(income_statement.net_income * 2.6) +
(performance_summary.cumulative_net_income * 10) + 
(manufacturer_sales.Allround.total_share_pct * 100 * 12.34) +
(stock_price * 6.45) 

These are the costs that will be calculated after we manually review the suggestions and proceed with and run the simulation on. 

Since there are tonnes of knobs, we have made an optimization strategy to try and reduce the search space. We want to first optimize for budgets, before we really play around with internals knobs. Since a lot of these knobs are mathematically related, we have a series of simple calculations that will help us reduce the domain and the options we have. 
For starters, we have the total budget - this is given on the number on the top of each of the decisions page. (not remaining budget but actual budget)
We obviously cannot exceed this total budget, thus the summation of all budgets must come under the total budget. For this, we want to introduce a buffer of 750000 i.e., Total Budget - 750000 must STRICTLY NOT BE EXCEEDED. Total Budget = SF_Size + Advertising_Size + Promotion_Size + Leftover that we do NOT use (Remaining). 
1) We must first size for 
1) FOR SF_SIZE (SF Budget) - we can reduce the Sales Force calculation and knobs into something much easier given we know the relations
   1) We want to use budget to backcalculate the number of people required with respect to the previous headcount/sales force. This information will be available in the decisions_periodN.json file. 
   2) Overall, the budget is ((current_total_sales_force - previous_total_sales_force + 0.15*previous_total_sales_force)*New_hire_training_per_person) + current_total_sales_force*(current_total_sales_force*(salary_per_person+expenses_per_person))
   3) Using the previous data from the json, we can calculate the number of new people required. 
   4) These people should be divided up equally between all buckets (one by one)
   5) Thus, the optimizer will optimize for the budget (or give a suggested value/point for the total budget), and then you need to backcalculate the number of people for each sales force branch given the previous sales force branch. You must refer to the structure in the json to understand. Ask questions as necessary. 
2) FOR Advertising_Size
   1) Advertising Budget (ad_budget1) is 1 knob that the optimizer must decide. 
   2) We want to then modify the ad messaging only - the ones to optimize are "benefit_msg1", "compare_msg1", "primary_msg1", and "reminder_msg1"
   3) "benefit_msg1", "compare_msg1", "primary_msg1", and "reminder_msg1" are percentages of the budget - they should add up to 100. 
   4) We want to lock "compare_msg1" equal to 5 always, and "primary_msg1" equal to 0 always
   5) This leaves us with "benefit_msg1" and "reminder_msg1" - these are two knobs that must add up to 95. 
   6) We want to keep everything else the exact same. 
   7) This means ADVERTISING SIZE has three knobs. 
3) For Promotion
   1) We want to always lock all "allowance1-n" to 16.66
   2) We want to always lock all "coop_ad1-n" to true
   3) We want to always lock all "display_ad1-n" to true
   4) We want to always lock "coupon_amt1" to 1
   5) We want to always lock "trial_budget1" to 0
   6) coop_ad_budget1 + coupon_budget1 + display_budget1 = Promotion Budget. This must be added to other budgets to get the total budget. 
Thus, on the budget size of things, we finally have these knobs, 
1) Total Budget = SF_Budget + ad_budget1 + coop_ad_budget1 + coupon_budget1 + display_budget1. (Using SF_Budget, we backcalculate how to dispense new employees)
2) Then, the other two knobs are "benefit_msg1" and "reminder_msg1"

For Decisions - Pricing, we have the five knobs:
1) We want to tweak discount knobs (inputs - disc1-1, disc1-2, disc1-3, disc1-4) between 15-75
2) We want to tweak inputs - msrp1 between 5.3 and 5.5.

Given this optimization strategy, your task is to study the codebase and any relevant files with upto 100 parallel subagents. Then, decide on the flow using the currently developed scripts that perform the scrape of excel (uv run python -m src.pipeline --periods 1) and the previous decisions (since it is required for some calculations - uv run python -m src.decision_scraper --periods 1). Then suggest a value. I will modify said values and tell the code when I am done modifying. Then apply my modified set values. Then, I will run the simulation (STRICTLY DO NOT RUN THE SIMULATION YOURSELF EVER), and then I will tell you the simulation has been run and you should scrape the values of year2. Then, we will repeat for the next run. You should manage the runs, and think about how you would handle all this data and keep it neat and clean. You should also make neat, detailed plots of each of the functions (i.e., the objective or cost function, the acqusition function, and the surrogate function if present) with respect to the knobs we are tuning. 
We have already implemented a script and strategy for years 1 and 2. You simply need to duplicate it and make it happen for year 0 and year 1 and keep it separated. 
