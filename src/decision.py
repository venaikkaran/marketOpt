"""Decision vector for PharmaSim optimization.

Represents the controllable variables for Allstar (company) / Allround (brand)
that the optimizer can adjust between simulation periods.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields


@dataclass
class DecisionVector:
    """All controllable decision variables for one simulation period.

    Variables are grouped by decision category. Bounds are approximate
    and may need tuning based on PharmaSim's actual constraints.
    """

    # -- Pricing --
    msrp: float = 0.0

    # -- Formulation --
    analgesic_mg: float = 0.0
    antihistamine_mg: float = 0.0
    decongestant_mg: float = 0.0
    cough_suppressant_mg: float = 0.0
    expectorant_mg: float = 0.0
    alcohol_pct: float = 0.0

    # -- Advertising --
    media_expenditure: float = 0.0  # in millions (e.g. 20.0 = $20M)
    ad_agency: str = ""
    primary_pct: float = 0.0
    benefits_pct: float = 0.0
    comparison_pct: float = 0.0
    reminder_pct: float = 0.0  # typically 1.0 - primary - benefits - comparison

    # -- Sales Force (headcount) --
    sf_direct_independent: float = 0.0
    sf_direct_chain: float = 0.0
    sf_direct_grocery: float = 0.0
    sf_direct_convenience: float = 0.0
    sf_direct_mass: float = 0.0
    sf_indirect_wholesaler: float = 0.0
    sf_indirect_merchandisers: float = 0.0
    sf_indirect_detailers: float = 0.0

    # -- Promotion --
    promotional_allowance_pct: float = 0.0
    coop_advertising: float = 0.0
    point_of_purchase: float = 0.0
    trial_size: float = 0.0
    coupon_amount: float = 0.0

    # Numeric-only fields for optimizer (excludes ad_agency)
    _NUMERIC_FIELDS: tuple[str, ...] = (
        "msrp",
        "analgesic_mg",
        "antihistamine_mg",
        "decongestant_mg",
        "cough_suppressant_mg",
        "expectorant_mg",
        "alcohol_pct",
        "media_expenditure",
        "primary_pct",
        "benefits_pct",
        "comparison_pct",
        "reminder_pct",
        "sf_direct_independent",
        "sf_direct_chain",
        "sf_direct_grocery",
        "sf_direct_convenience",
        "sf_direct_mass",
        "sf_indirect_wholesaler",
        "sf_indirect_merchandisers",
        "sf_indirect_detailers",
        "promotional_allowance_pct",
        "coop_advertising",
        "point_of_purchase",
        "trial_size",
        "coupon_amount",
    )

    @classmethod
    def from_year_data(cls, yd) -> DecisionVector:
        """Extract the decision reflected in YearData reports.

        YearN reports show the effects of Decision(N-1).
        E.g., Year1 data reflects Decision0; Year2 data reflects Decision1.
        This does NOT extract the pending decision to be made at YearN.
        """
        dv = cls()

        # Pricing
        if yd.performance_summary:
            dv.msrp = yd.performance_summary.msrp or 0.0

        # Formulation
        bf = yd.brand_formulations.get("Allround")
        if bf:
            dv.analgesic_mg = bf.analgesic_mg or 0.0
            dv.antihistamine_mg = bf.antihistamine_mg or 0.0
            dv.decongestant_mg = bf.decongestant_mg or 0.0
            dv.cough_suppressant_mg = bf.cough_suppressant_mg or 0.0
            dv.expectorant_mg = bf.expectorant_mg or 0.0
            dv.alcohol_pct = bf.alcohol_pct or 0.0

        # Advertising
        ad = yd.advertising.get("Allround")
        if ad:
            dv.media_expenditure = ad.media_expenditure or 0.0
            dv.ad_agency = ad.ad_agency or ""
            dv.primary_pct = ad.primary_pct or 0.0
            dv.benefits_pct = ad.benefits_pct or 0.0
            dv.comparison_pct = ad.comparison_pct or 0.0
            dv.reminder_pct = ad.reminder_pct or 0.0

        # Sales Force (Allstar is the company)
        sf = yd.sales_force.get("Allstar")
        if sf:
            dv.sf_direct_independent = sf.direct_independent_drugstores or 0.0
            dv.sf_direct_chain = sf.direct_chain_drugstores or 0.0
            dv.sf_direct_grocery = sf.direct_grocery_stores or 0.0
            dv.sf_direct_convenience = sf.direct_convenience_stores or 0.0
            dv.sf_direct_mass = sf.direct_mass_merchandisers or 0.0
            dv.sf_indirect_wholesaler = sf.indirect_wholesaler_support or 0.0
            dv.sf_indirect_merchandisers = sf.indirect_merchandisers or 0.0
            dv.sf_indirect_detailers = sf.indirect_detailers or 0.0

        # Promotion data comes from two parsed sources:
        # - promotion_reports: numeric fields for Allround's actual spending
        # - promotions: competitor-view summary, where trial_size is a "Yes"/"" flag
        promo = yd.promotions.get("Allround")
        promo_report = yd.promotion_reports.get("Allround")
        if promo or promo_report:
            if promo and promo.promotional_allowance_pct is not None:
                dv.promotional_allowance_pct = promo.promotional_allowance_pct
            elif (
                promo_report
                and promo_report.promotional_allowance is not None
            ):
                dv.promotional_allowance_pct = promo_report.promotional_allowance

            if promo_report and promo_report.coop_advertising is not None:
                dv.coop_advertising = promo_report.coop_advertising
            elif promo and promo.coop_advertising is not None:
                dv.coop_advertising = promo.coop_advertising

            if promo_report and promo_report.point_of_purchase is not None:
                dv.point_of_purchase = promo_report.point_of_purchase
            elif promo and promo.point_of_purchase is not None:
                dv.point_of_purchase = promo.point_of_purchase

            if promo_report and promo_report.trial_size is not None:
                dv.trial_size = promo_report.trial_size

            if promo and promo.coupon_amount is not None:
                dv.coupon_amount = promo.coupon_amount
            elif promo_report and promo_report.coupon_amount is not None:
                dv.coupon_amount = promo_report.coupon_amount

        return dv

    def to_dict(self) -> dict:
        """Serialize to dict (for metadata.json)."""
        d = asdict(self)
        d.pop("_NUMERIC_FIELDS", None)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> DecisionVector:
        """Deserialize from dict."""
        valid = {f.name for f in fields(cls) if not f.name.startswith("_")}
        return cls(**{k: v for k, v in d.items() if k in valid})

    @classmethod
    def field_names(cls) -> list[str]:
        """Ordered numeric field names matching to_array() positions."""
        return list(cls._NUMERIC_FIELDS)

    def to_array(self) -> list[float]:
        """Flatten numeric fields to a list for optimizer consumption."""
        return [float(getattr(self, f)) for f in self._NUMERIC_FIELDS]

    @classmethod
    def from_array(cls, arr: list[float], ad_agency: str = "") -> DecisionVector:
        """Reconstruct from a flat numeric array."""
        dv = cls(ad_agency=ad_agency)
        for name, val in zip(cls._NUMERIC_FIELDS, arr):
            setattr(dv, name, val)
        return dv
