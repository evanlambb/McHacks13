/*
 * Decompiled with CFR 0.152.
 */
package ca.mc.exchange_simulator.simulator;

import ca.mc.exchange_simulator.core.DeterministicRandom;
import ca.mc.exchange_simulator.core.Fill;
import ca.mc.exchange_simulator.core.OrderBook;
import ca.mc.exchange_simulator.scenario.ScenarioConfig;
import ca.mc.exchange_simulator.simulator.EventManager;
import ca.mc.exchange_simulator.traders.BaseTrader;
import ca.mc.exchange_simulator.traders.FundamentalTrader;
import ca.mc.exchange_simulator.traders.InstitutionalTrader;
import ca.mc.exchange_simulator.traders.MarketMaker;
import ca.mc.exchange_simulator.traders.MomentumTrader;
import ca.mc.exchange_simulator.traders.NoiseTrader;
import ca.mc.exchange_simulator.traders.SpikingTrader;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class SimulationContext {
    private String runId;
    private String studentId;
    private String scenarioId;
    private DeterministicRandom rng;
    private OrderBook orderBook;
    private List<BaseTrader> traders;
    private ScenarioConfig scenario;
    private EventManager eventManager;
    public static final double INITIAL_BALANCE = 100000.0;
    private int currentStep = 0;
    private double fundamentalValue = 4500.0;
    private double currentVolatility = 0.02;
    private int inventory = 0;
    private double pnl = 0.0;
    private long stepStart = 0L;
    private long accumulatedTime = 0L;
    private List<Fill> allFills = new ArrayList<Fill>();
    private List<Double> equityCurve = new ArrayList<Double>();
    private int maxInventory = 0;
    private List<Fill> stepFills = Collections.synchronizedList(new ArrayList());
    private int aggressiveVolume = 0;
    private boolean blowup = false;
    private String blowupReason;

    public double getEquity(double currentPrice) {
        return 100000.0 + this.pnl + (double)this.inventory * currentPrice;
    }

    public SimulationContext(String runId, String studentId, String scenarioId, long seed, ScenarioConfig scenario) {
        this.runId = runId;
        this.studentId = studentId;
        this.scenarioId = scenarioId;
        this.rng = new DeterministicRandom(seed);
        this.orderBook = new OrderBook();
        this.scenario = scenario;
        if (scenario.getMarketConfig() != null && scenario.getMarketConfig().containsKey("initialFundamentalValue")) {
            this.fundamentalValue = ((Number)scenario.getMarketConfig().get("initialFundamentalValue")).doubleValue();
        }
        if (scenario.getMarketConfig() != null && scenario.getMarketConfig().containsKey("volatility")) {
            this.currentVolatility = ((Number)scenario.getMarketConfig().get("volatility")).doubleValue();
        }
    }

    public void initializeTraders() {
        int i;
        double delta;
        double chi;
        double rho;
        int i2;
        int count;
        this.traders = new ArrayList<BaseTrader>();
        Map<String, Object> config = this.scenario.getTraders();
        if (config == null) {
            config = new HashMap<String, Object>();
        }
        if (config == null) {
            config = new HashMap<String, Object>();
        }
        if (config.containsKey("fundamental")) {
            Map ftConfig = (Map)config.get("fundamental");
            count = ((Number)ftConfig.getOrDefault("count", 0)).intValue();
            double k1 = ftConfig.containsKey("kappa1") ? ((Number)ftConfig.get("kappa1")).doubleValue() : 0.5;
            double k2 = ftConfig.containsKey("kappa2") ? ((Number)ftConfig.get("kappa2")).doubleValue() : 0.001;
            int interval = ((Number)ftConfig.getOrDefault("interval", 1)).intValue();
            for (i2 = 0; i2 < count; ++i2) {
                this.traders.add(new FundamentalTrader("ft_" + i2, this.rng, this.fundamentalValue, k1, k2, count, interval));
            }
        }
        if (config.containsKey("momentumLongTerm")) {
            Map ltConfig = (Map)config.get("momentumLongTerm");
            count = ((Number)ltConfig.getOrDefault("count", 0)).intValue();
            rho = ltConfig.containsKey("decayRate") ? ((Number)ltConfig.get("decayRate")).doubleValue() : ((Number)ltConfig.getOrDefault("alpha", 0.01)).doubleValue();
            chi = ltConfig.containsKey("chi") ? ((Number)ltConfig.get("chi")).doubleValue() : ((Number)ltConfig.getOrDefault("beta", 50.0)).doubleValue();
            double psi = ltConfig.containsKey("psi") ? ((Number)ltConfig.get("psi")).doubleValue() : chi * 0.3;
            delta = ((Number)ltConfig.getOrDefault("cancelRate", 0.05)).doubleValue();
            for (i = 0; i < count; ++i) {
                this.traders.add(new MomentumTrader("mt_lt_" + i, this.rng, rho, chi, psi, delta, count));
            }
        }
        if (config.containsKey("momentumShortTerm")) {
            Map stConfig = (Map)config.get("momentumShortTerm");
            count = ((Number)stConfig.getOrDefault("count", 0)).intValue();
            rho = stConfig.containsKey("decayRate") ? ((Number)stConfig.get("decayRate")).doubleValue() : ((Number)stConfig.getOrDefault("alpha", 0.9)).doubleValue();
            chi = stConfig.containsKey("chi") ? ((Number)stConfig.get("chi")).doubleValue() : ((Number)stConfig.getOrDefault("beta", 80.0)).doubleValue();
            double psi = stConfig.containsKey("psi") ? ((Number)stConfig.get("psi")).doubleValue() : chi * 0.3;
            delta = ((Number)stConfig.getOrDefault("cancelRate", 0.05)).doubleValue();
            for (i = 0; i < count; ++i) {
                this.traders.add(new MomentumTrader("mt_st_" + i, this.rng, rho, chi, psi, delta, count));
            }
        }
        if (config.containsKey("noise")) {
            Map ntConfig = (Map)config.get("noise");
            count = ((Number)ntConfig.getOrDefault("count", 0)).intValue();
            double eta = ntConfig.containsKey("eta") ? ((Number)ntConfig.get("eta")).doubleValue() : ((Number)ntConfig.getOrDefault("sigma", 5.0)).doubleValue();
            double kappa = ((Number)ntConfig.getOrDefault("kappa", 0.25)).doubleValue();
            double delta2 = ((Number)ntConfig.getOrDefault("cancelRate", 0.05)).doubleValue();
            for (int i3 = 0; i3 < count; ++i3) {
                this.traders.add(new NoiseTrader("nt_" + i3, this.rng, eta, kappa, delta2, count, this.fundamentalValue));
            }
        }
        if (config.containsKey("marketMaker")) {
            Map mmConfig = (Map)config.get("marketMaker");
            count = ((Number)mmConfig.getOrDefault("count", 0)).intValue();
            int inventoryLimit = ((Number)mmConfig.getOrDefault("inventoryLimit", 5000)).intValue();
            int safeInventory = ((Number)mmConfig.getOrDefault("safeInventory", 2000)).intValue();
            int restPeriod = ((Number)mmConfig.getOrDefault("restPeriod", 600)).intValue();
            double spreadEdge = mmConfig.containsKey("maxEdge") ? ((Number)mmConfig.get("maxEdge")).doubleValue() : ((Number)mmConfig.getOrDefault("spreadEdge", 2.0)).doubleValue();
            double gamma = ((Number)mmConfig.getOrDefault("gamma", 0.8)).doubleValue();
            double deltaMM = ((Number)mmConfig.getOrDefault("delta", 0.3)).doubleValue();
            for (int i4 = 0; i4 < count; ++i4) {
                this.traders.add(new MarketMaker("mm_" + i4, this.rng, inventoryLimit, safeInventory, restPeriod, spreadEdge, gamma, deltaMM, this.fundamentalValue));
            }
        }
        if (config.containsKey("institutional")) {
            Map instConfig = (Map)config.get("institutional");
            count = ((Number)instConfig.getOrDefault("count", 0)).intValue();
            int initialInventory = ((Number)instConfig.getOrDefault("initialInventory", 0)).intValue();
            double percentageOfVolume = ((Number)instConfig.getOrDefault("percentageOfVolume", 9)).doubleValue() / 100.0;
            int orderIntervalSteps = ((Number)instConfig.getOrDefault("orderInterval", 12)).intValue() * 10;
            int startStep = 0;
            if (instConfig.containsKey("startStep")) {
                startStep = ((Number)instConfig.get("startStep")).intValue();
            } else if (instConfig.containsKey("startTime")) {
                String startTime = (String)instConfig.get("startTime");
                startStep = this.parseTimeToStep(startTime);
            }
            for (i2 = 0; i2 < count; ++i2) {
                this.traders.add(new InstitutionalTrader("inst_" + i2, this.rng, initialInventory, percentageOfVolume, orderIntervalSteps, startStep));
            }
        }
        if (config.containsKey("spiking")) {
            Map spkConfig = (Map)config.get("spiking");
            count = ((Number)spkConfig.getOrDefault("count", 0)).intValue();
            int spikeLength = ((Number)spkConfig.getOrDefault("spikeLength", 4)).intValue();
            double activationProbability = ((Number)spkConfig.getOrDefault("activationProbability", 0.005)).doubleValue();
            int orderVolume = ((Number)spkConfig.getOrDefault("orderVolume", 100)).intValue();
            for (int i5 = 0; i5 < count; ++i5) {
                this.traders.add(new SpikingTrader("spk_" + i5, this.rng, spikeLength, activationProbability, orderVolume));
            }
        }
    }

    private int parseTimeToStep(String timeStr) {
        try {
            String[] parts = timeStr.split(":");
            int hours = Integer.parseInt(parts[0]);
            int minutes = Integer.parseInt(parts[1]);
            int seconds = parts.length > 2 ? Integer.parseInt(parts[2]) : 0;
            int marketOpenHour = 8;
            int totalSeconds = (hours - marketOpenHour) * 3600 + minutes * 60 + seconds;
            return totalSeconds * 10;
        }
        catch (Exception e) {
            return 0;
        }
    }

    public String getRunId() {
        return this.runId;
    }

    public String getStudentId() {
        return this.studentId;
    }

    public String getScenarioId() {
        return this.scenarioId;
    }

    public ScenarioConfig getScenario() {
        return this.scenario;
    }

    public OrderBook getOrderBook() {
        return this.orderBook;
    }

    public List<BaseTrader> getTraders() {
        return this.traders;
    }

    public int getCurrentStep() {
        return this.currentStep;
    }

    public void setCurrentStep(int step) {
        this.currentStep = step;
    }

    public DeterministicRandom getRng() {
        return this.rng;
    }

    public EventManager getEventManager() {
        return this.eventManager;
    }

    public void setEventManager(EventManager eventManager) {
        this.eventManager = eventManager;
    }

    public double getFundamentalValue() {
        return this.fundamentalValue;
    }

    public void updateFundamentalValue(double delta) {
        this.fundamentalValue += delta;
    }

    public double getCurrentVolatility() {
        return this.currentVolatility;
    }

    public void setCurrentVolatility(double volatility) {
        this.currentVolatility = volatility;
    }

    public synchronized void updateInventoryAndPnL(double tradePrice, int qty, String side) {
        if (side.equals("BUY")) {
            this.inventory += qty;
            this.pnl -= (double)qty * tradePrice;
        } else {
            this.inventory -= qty;
            this.pnl += (double)qty * tradePrice;
        }
        int absInventory = Math.abs(this.inventory);
        if (absInventory > this.maxInventory) {
            this.maxInventory = absInventory;
        }
    }

    public int getInventory() {
        return this.inventory;
    }

    public double getPnL() {
        return this.pnl;
    }

    public int getMaxInventory() {
        return this.maxInventory;
    }

    public void setStepStart(long stepStart) {
        this.stepStart = stepStart;
    }

    public long getStepStart() {
        return this.stepStart;
    }

    public void addTime(long duration) {
        this.accumulatedTime += duration;
    }

    public long getAccumulatedTime() {
        return this.accumulatedTime;
    }

    public void addFills(List<Fill> fills) {
        this.stepFills.addAll(fills);
    }

    /*
     * WARNING - Removed try catching itself - possible behaviour change.
     */
    public List<Fill> getStepFills() {
        List<Fill> list = this.stepFills;
        synchronized (list) {
            return new ArrayList<Fill>(this.stepFills);
        }
    }

    public void clearStepFills() {
        this.stepFills.clear();
    }

    public synchronized void incrementAggressiveVolume(int qty) {
        this.aggressiveVolume += qty;
    }

    public int getAggressiveVolume() {
        return this.aggressiveVolume;
    }

    public void setBlowup(boolean blowup) {
        this.blowup = blowup;
    }

    public boolean isBlowup() {
        return this.blowup;
    }

    public String getBlowupReason() {
        return this.blowupReason;
    }

    public void setBlowupReason(String blowupReason) {
        this.blowupReason = blowupReason;
    }

    public List<Fill> getAllFills() {
        return this.allFills;
    }

    public void recordFill(Fill fill) {
        if (fill.getStudentId().equals(this.studentId)) {
            this.allFills.add(fill);
        }
    }

    public List<Double> getEquityCurve() {
        return this.equityCurve;
    }

    public void recordEquity(double equity) {
        this.equityCurve.add(equity);
    }
}
