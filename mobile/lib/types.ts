export type SaiAction = "buy" | "sell" | "hold" | "watch" | string;

export interface DeployFingerprint {
  appVersion?: string;
  environment?: "local" | "render" | string;
  build?: string | null;
  gitCommit?: string | null;
  gitBranch?: string | null;
  host?: string | null;
  serviceId?: string | null;
  serviceName?: string | null;
  instanceId?: string | null;
  label?: string;
}

export interface ApiConfig {
  version?: string;
  appVersion?: string;
  build?: string | null;
  environment?: string;
  host?: string | null;
  gitCommit?: string | null;
  gitBranch?: string | null;
  serviceId?: string | null;
  serviceName?: string | null;
  deploy?: DeployFingerprint;
  assessmentProvider?: string;
  assessmentMode?: string;
  llmConfigured?: boolean;
  syncIntervalSeconds?: number;
  importVersion?: number;
  geminiModel?: string | null;
  docs?: Record<string, string>;
}

export interface Overview {
  symbolCount?: number;
  holdingCount?: number;
  watchlistOnlyCount?: number;
  totalMarketValue?: number | null;
  totalDayChange?: number | null;
  totalDayChangePct?: number | null;
  totalCostBasis?: number | null;
  unrealizedGain?: number | null;
  unrealizedGainPct?: number | null;
  totalAnnualDividend?: number | null;
  totalAnnualDividendYieldPct?: number | null;
  totalAnalystTargetValue?: number | null;
  totalAnalystUpsidePct?: number | null;
  totalPersonalTargetValue?: number | null;
  totalPersonalUpsidePct?: number | null;
  totalProjectedRoc?: number | null;
  totalProjectedRocPct?: number | null;
  pastProgress?: PastProgress | null;
  activeAlerts?: number;
  bestPerformer?: { symbol: string; gainPct?: number; gain?: number } | null;
  bestYtdPerformer?: { symbol: string; gainPct?: number; gain?: number } | null;
  pricesAsOf?: string | null;
  holdings?: Holding[];
  simulation?: {
    projectedValuation?: number | null;
    projectedUpsidePct?: number | null;
    netCashFlow?: number | null;
    totalNetGains?: number | null;
    buyLegs?: number;
    sellLegs?: number;
    scopeCount?: number;
    savedAt?: string | null;
  } | null;
  alerts?: Alert[];
  latestAssessments?: Assessment[];
}

export interface PastProgressWindow {
  valueThen?: number | null;
  valueNow?: number | null;
  returnPct?: number | null;
  spyReturnPct?: number | null;
  relativePct?: number | null;
  coverage?: {
    heldWithPrices?: number;
    heldTotal?: number;
    pct?: number;
  };
  /** Buy-and-hold market values at the window date (when API provides them). */
  holdings?: Array<{ symbol: string; marketValue?: number | null; value?: number | null }> | null;
}

export interface PastProgress {
  asOf?: string;
  definition?: string;
  windows?: {
    "1M"?: PastProgressWindow;
    "3M"?: PastProgressWindow;
  };
  ath?: {
    date?: string;
    value?: number | null;
    deltaValue?: number | null;
    deltaPct?: number | null;
    holdings?: Array<{ symbol: string; marketValue?: number | null; value?: number | null }> | null;
  } | null;
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
  companyName?: string | null;
  targetPrice?: number | null;
  analystTarget1y?: number | null;
  analystTargetLow?: number | null;
  analystTargetHigh?: number | null;
  tradeBelowPrice?: number | null;
  tradeBelowShares?: number | null;
  tradeAbovePrice?: number | null;
  tradeAboveShares?: number | null;
  buyBelow?: number | null;
  sellAbove?: number | null;
  annualDividend?: number | null;
  isStarred?: boolean;
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
  saiProposal?: TradingProposal;
  currentPrice?: number | null;
  dayChangePct?: number | null;
  quantity?: number | null;
  marketValue?: number | null;
  weightPct?: number | null;
  annualDividend?: number | null;
  unrealizedGain?: number | null;
  gainPct?: number | null;
  analystTarget1y?: number | null;
  analystTargetLow?: number | null;
  analystTargetHigh?: number | null;
  analystUpsidePct?: number | null;
  analystTargetValue?: number | null;
  personalTarget?: number | null;
  personalUpsidePct?: number | null;
  personalTargetValue?: number | null;
  tradeBelowPrice?: number | null;
  tradeBelowShares?: number | null;
  tradeAbovePrice?: number | null;
  tradeAboveShares?: number | null;
}

export interface Alert {
  id: number;
  symbol: string;
  type?: string;
  alert_type?: string;
  message?: string;
  price?: number | null;
  referenceValue?: number | null;
  reference_value?: number | null;
  fibLevel?: string | null;
  status?: string;
  createdAt?: string;
}

export interface Assessment {
  id?: number;
  symbol: string;
  action?: SaiAction;
  confidence?: string;
  rationale?: string;
  createdAt?: string;
  provider?: string;
  /** Optional Decision Framework scaffold — see docs/PROPOSAL_FRAMEWORK.md */
  proposal?: TradingProposal;
}

export interface TradingProposalScores {
  state?: number;
  trigger?: number;
  portfolioFit?: number;
  total?: number;
}

/** Additive API field; UI can ignore until a compact proposal card lands. */
export interface TradingProposal {
  schemaVersion?: number;
  action?: SaiAction | string;
  confidence?: string;
  authority?: string;
  scores?: TradingProposalScores;
  rationale?: string;
  actionSource?: string | null;
  fitExtensions?: Record<string, unknown>;
  bandBias?: {
    code?: string;
    label?: string;
    range?: string;
    advisory?: boolean;
    note?: string;
  };
  attention?: {
    flag?: boolean;
    level?: string | null;
    message?: string | null;
    bandAction?: string | null;
    saiAction?: string | null;
  };
  intent?: {
    code?: string;
    label?: string;
    inferred?: string;
    override?: string | null;
    source?: string;
  };
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
    watchItems?: string[];
    sentiment?: string;
    sentimentSource?: string;
    sentimentDetail?: string;
    assessedAt?: string;
    proposal?: TradingProposal;
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
    earningsGrowth?: number | null;
    operatingMargin?: number | null;
    companyName?: string | null;
    recommendationKey?: string | null;
    analystCount?: number | null;
    targetMean?: number | null;
    targetHigh?: number | null;
    targetLow?: number | null;
    beta?: number | null;
    debtToEquity?: number | null;
    freeCashflow?: number | null;
    ma50?: number | null;
    ma200?: number | null;
    high52w?: number | null;
    low52w?: number | null;
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
  chartTimelineFull?: {
    windowStart?: string;
    windowEnd?: string;
    startDate?: string;
    endDate?: string;
    points?: { date?: string; price?: number; volume?: number }[];
    span?: string;
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

export interface NoteSynthesis {
  summary?: string;
  sentiment?: string;
  growthTrajectory?: Array<{ metric?: string; growth?: string; period?: string }>;
  revenueProjections?: Array<{ target?: string; timeline?: string }>;
  catalystsToWatch?: Array<{ period?: string; metric?: string; threshold?: string }>;
  llmFallback?: boolean;
  llmError?: string;
  integratedSummary?: string;
}

export interface Note {
  id?: number;
  symbol?: string;
  date?: string;
  source?: string;
  text?: string;
  synthesis?: NoteSynthesis | null;
  synthesisProvider?: string | null;
  synthesizedAt?: string | null;
  createdAt?: string;
}

export interface TickerSearchHit {
  symbol: string;
  displaySymbol?: string;
  description?: string;
  type?: string;
}

export type TaxTrimPricingMode = "current" | "threshold";

export interface TaxTrimLossCandidate {
  symbol: string;
  held?: number;
  sellQtyMax?: number;
  sellPlanCap?: number | null;
  netLossMax?: number;
  cashGenerated?: number;
  execPrice?: number;
  execSource?: string | null;
  gainPct?: number;
  residualLossPct?: number | null;
  analystUpsidePct?: number | null;
  lossScore?: number;
  score?: number;
  saiAction?: string;
  saiConfidence?: string;
  hasSellPlan?: boolean;
  isTrim?: boolean;
}

export interface TaxTrimWinnerCandidate {
  symbol: string;
  held?: number;
  sellQtyMax?: number;
  sellPlanCap?: number | null;
  netGainsMax?: number;
  cashGenerated?: number;
  execPrice?: number;
  execSource?: string | null;
  gainPct?: number | null;
  weightPct?: number | null;
  analystUpsidePct?: number | null;
  personalUpsidePct?: number | null;
  headroomPct?: number;
  trimScore?: number;
  score?: number;
  saiAction?: string;
  saiConfidence?: string;
  hasSellPlan?: boolean;
  isTrim?: boolean;
  suggestShares?: number;
  suggestGain?: number;
  suggestCash?: number;
}

export interface TaxTrimProposal {
  pricingMode: TaxTrimPricingMode;
  lossScoreThreshold: number;
  trimScoreThreshold: number;
  matchLossPool: boolean;
  lossPool: number;
  allCandidatePool: number;
  allTrimCandidatePool: number;
  selectedTrimPool: number;
  offsetGain: number;
  remainingLoss: number;
  allocTarget: number;
  lossSells: {
    candidates: TaxTrimLossCandidate[];
    selectedCount: number;
    candidateCount: number;
  };
  winnerTrims: {
    candidates: TaxTrimWinnerCandidate[];
    selectedCount: number;
    candidateCount: number;
  };
  picks: TaxTrimWinnerCandidate[];
  scopedSymbols?: string[] | null;
}

export interface TaxTrimOrderBook {
  v: number;
  type: string;
  capturedAt: string;
  settings: {
    pricingMode?: TaxTrimPricingMode;
    lossScoreThreshold?: number;
    trimScoreThreshold?: number;
    matchLossPool?: boolean;
    selectedSymbols?: string[];
  };
  summary: {
    lossPool?: number;
    offsetGain?: number;
    remainingLoss?: number;
    selectedLossCount?: number;
    proposedTrimCount?: number;
    orderCount?: number;
    estSellCash?: number;
  };
  orders: Array<{
    side: string;
    kind: string;
    symbol: string;
    shares: number;
    limit?: number;
    execSource?: string | null;
    estLoss?: number;
    estGain?: number;
    estCash?: number;
    lossScore?: number;
    trimScore?: number;
  }>;
  proposal?: TaxTrimProposal;
}

