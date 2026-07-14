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

export interface FundamentalsGroups {
  profile?: Record<string, unknown>;
  valuation?: Record<string, unknown>;
  growthProfitability?: Record<string, unknown>;
  financialHealth?: Record<string, unknown>;
  analyst?: Record<string, unknown>;
  priceRange?: Record<string, unknown>;
}

export interface FundamentalsRow {
  symbol: string;
  currentPrice?: number | null;
  dayChangePct?: number | null;
  fundamentals?: FundamentalsGroups;
}

export interface FundamentalsFeed {
  symbols: FundamentalsRow[];
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
  annualDividend?: number | null;
  notes?: Note[];
  latestAssessment?: SaiSummary | null;
}

export interface Holding {
  symbol: string;
  quantity?: number;
  costBasis?: number | null;
  totalCost?: number | null;
  purchaseDate?: string | null;
  currentPrice?: number | null;
  marketValue?: number | null;
  unrealizedGain?: number | null;
  gainPct?: number | null;
  dayChangePct?: number | null;
  weightPct?: number | null;
  annualDividend?: number | null;
  analystTarget1y?: number | null;
  analystTargetValue?: number | null;
  analystUpsidePct?: number | null;
  personalTarget?: number | null;
  personalTargetValue?: number | null;
  personalUpsidePct?: number | null;
}

export interface PortfolioRow {
  symbol: string;
  saiAction?: SaiAction;
  saiConfidence?: string;
  currentPrice?: number | null;
  dayChangePct?: number | null;
  quantity?: number | null;
  marketValue?: number | null;
  weightPct?: number | null;
  annualDividend?: number | null;
  unrealizedGain?: number | null;
  gainPct?: number | null;
  analystTarget1y?: number | null;
  analystUpsidePct?: number | null;
  analystTargetValue?: number | null;
  personalTarget?: number | null;
  personalUpsidePct?: number | null;
  personalTargetValue?: number | null;
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
  id?: number;
  symbol: string;
  oldAction?: string;
  newAction?: string;
  oldConfidence?: string;
  newConfidence?: string;
  createdAt?: string;
  changedAt?: string;
  rationale?: string;
  provider?: string;
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
    rationale?: string;
    thesis?: string;
    drivers?: string[];
    reasons?: string[];
    sentiment?: string;
    sentimentSource?: string;
    sentimentDetail?: string;
  };
  screening?: {
    score?: number | null;
    pScore?: number | null;
    upsidePct?: number | null;
    flags?: string[];
    techStance?: string;
  };
  positionMechanics?: {
    entryDate?: string;
    purchaseDate?: string;
    sharesOwned?: number;
    quantity?: number;
    entryCapital?: number | null;
    totalGain?: number | null;
    totalGainPct?: number | null;
    currentValue?: number | null;
    marketValue?: number | null;
    unrealizedGain?: number | null;
    gainPct?: number | null;
    costBasis?: number | null;
    personalTarget?: number | null;
    personalTargetValue?: number | null;
    personalUpsidePct?: number | null;
    weightPct?: number | null;
  };
  valuation?: {
    pScore?: number | null;
    estDividend?: number | null;
    trailingPe?: number | null;
    forwardPe?: number | null;
    pegRatio?: number | null;
    revenueGrowth?: number | null;
    operatingMargin?: number | null;
    companyName?: string | null;
  };
  technicalAdvisory?: {
    stance?: string;
    message?: string;
  };
  confluence?: ConfluencePayload | null;
  fib?: FibPayload | null;
  fibBlueprint?: {
    swingHigh?: number | null;
    swingLow?: number | null;
    levels?: { key?: string; label?: string; price?: number; color?: string }[];
    anchorNote?: string;
  } | null;
  nearestFib?: {
    fib?: string;
    level?: { label?: string; price?: number };
    distancePct?: number | null;
  } | null;
  chartPatterns?: ChartPatternPayload[];
  volume?: VolumePayload | null;
  trendWaves?: TrendWavePayload[];
  importedFibLevels?: ImportedFibLevel[];
  chartTimeline?: {
    windowStart?: string;
    windowEnd?: string;
    points?: { date?: string; price?: number; volume?: number }[];
  } | null;
  alerts?: Alert[];
  assessments?: Assessment[];
}

export interface ConfluencePayload {
  bias?: string;
  score?: number;
  score100?: number;
  strength?: string;
  agreeCount?: number;
  conflictCount?: number;
  totalSignals?: number;
  votes?: {
    agent?: string;
    direction?: string;
    label?: string;
    detail?: string;
  }[];
  agreements?: string[];
  conflicts?: string[];
  summary?: string;
  message?: string;
  watch?: {
    headline?: string;
    limitingLens?: string;
    preconditions?: string[];
  };
}

export interface FibPayload {
  swingHigh?: number | null;
  swingLow?: number | null;
  levels?: { label?: string; ratio?: number; price?: number }[];
  anchorNote?: string;
}

export interface ChartPatternPayload {
  name?: string;
  type?: string;
  confidence?: number;
  status?: string;
  keyLevel?: { label?: string; price?: number };
  target?: number;
  summary?: string;
  points?: { date?: string; price?: number; role?: string }[];
  validation?: { verdict?: string; reasons?: string[] };
}

export interface VolumePayload {
  rvol?: number | null;
  avgVolume20?: number | null;
  obvSlopePct?: number | null;
  obvLabel?: string;
  priceDirection?: string;
  state?: string;
}

export interface TrendWavePayload {
  label?: string;
  direction?: string;
  movePct?: number | null;
  startDate?: string;
  endDate?: string;
  priceStart?: number | null;
  priceEnd?: number | null;
  legPattern?: string;
  type?: string;
}

export interface ImportedFibLevel {
  key?: string;
  label?: string;
  shortLabel?: string;
  price?: number;
  color?: string;
}

export interface Note {
  id?: number;
  symbol?: string;
  date?: string;
  source?: string;
  text?: string;
}
