export type SaiAction = "buy" | "sell" | "hold" | "watch" | string;

export interface ApiConfig {
  version?: string;
  assessmentProvider?: string;
  syncIntervalSeconds?: number;
}

export interface Overview {
  symbolCount?: number;
  holdingCount?: number;
  watchlistOnlyCount?: number;
  totalMarketValue?: number | null;
  totalDayChange?: number | null;
  totalDayChangePct?: number | null;
  unrealizedGain?: number | null;
  unrealizedGainPct?: number | null;
  activeAlerts?: number;
  bestPerformer?: { symbol: string; gainPct?: number; gain?: number } | null;
  bestYtdPerformer?: { symbol: string; gainPct?: number; gain?: number } | null;
  pricesAsOf?: string | null;
  holdings?: Holding[];
  alerts?: Alert[];
  latestAssessments?: Assessment[];
}

export interface SaiSummary {
  action?: SaiAction;
  confidence?: string;
}

export interface PortfolioSymbol {
  symbol: string;
  currentPrice?: number | null;
  dayChangePct?: number | null;
  targetPrice?: number | null;
  analystTarget1y?: number | null;
  buyBelow?: number | null;
  sellAbove?: number | null;
  notes?: Note[];
  latestAssessment?: SaiSummary | null;
}

export interface Holding {
  symbol: string;
  quantity?: number;
  currentPrice?: number | null;
  marketValue?: number | null;
  unrealizedGain?: number | null;
  gainPct?: number | null;
  dayChangePct?: number | null;
  weightPct?: number | null;
}

export interface Alert {
  id: number;
  symbol: string;
  type?: string;
  alert_type?: string;
  message?: string;
  price?: number | null;
  reference_value?: number | null;
  status?: string;
}

export interface Assessment {
  id?: number;
  symbol: string;
  action?: SaiAction;
  confidence?: string;
  rationale?: string;
  createdAt?: string;
  provider?: string;
}

export interface RecommendationChange {
  symbol: string;
  oldAction?: string;
  newAction?: string;
  changedAt?: string;
  rationale?: string;
}

export interface NewsItem {
  symbol: string;
  title?: string;
  publisher?: string;
  published?: string;
  link?: string;
  summary?: string;
  relevanceScore?: number | null;
}

export interface NewsFeed {
  recommendationChanges?: RecommendationChange[];
  topNews?: NewsItem[];
  newsCheckedAt?: string;
}

export interface InspectorPayload {
  symbol: string;
  companyName?: string | null;
  quote?: PortfolioSymbol;
  holding?: Holding | null;
  recommendation?: {
    action?: SaiAction;
    confidence?: string;
    headline?: string;
    reasons?: string[];
  };
  screening?: {
    pScore?: number | null;
    upsidePct?: number | null;
    flags?: string[];
  };
  positionMechanics?: {
    quantity?: number;
    marketValue?: number | null;
    unrealizedGain?: number | null;
    gainPct?: number | null;
    weightPct?: number | null;
  };
  alerts?: Alert[];
  assessments?: Assessment[];
  valuation?: Record<string, unknown>;
}

export interface Note {
  id?: number;
  symbol?: string;
  date?: string;
  source?: string;
  text?: string;
}
