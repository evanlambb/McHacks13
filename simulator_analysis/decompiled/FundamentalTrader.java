/*
 * Decompiled with CFR 0.152.
 */
package ca.mc.exchange_simulator.traders;

import ca.mc.exchange_simulator.core.DeterministicRandom;
import ca.mc.exchange_simulator.core.MarketSnapshot;
import ca.mc.exchange_simulator.core.Order;
import ca.mc.exchange_simulator.traders.BaseTrader;
import java.util.ArrayList;
import java.util.List;

public class FundamentalTrader
extends BaseTrader {
    private double fundamentalValue;
    private double kappa1 = 0.5;
    private double kappa2 = 0.001;
    private int numTraders = 30;
    private int updateInterval = 1;

    public FundamentalTrader(String traderId, DeterministicRandom rng, double fundamentalValue) {
        this(traderId, rng, fundamentalValue, 0.5, 0.001, 30, 1);
    }

    public FundamentalTrader(String traderId, DeterministicRandom rng, double fundamentalValue, double kappa1, double kappa2) {
        this(traderId, rng, fundamentalValue, kappa1, kappa2, 30, 1);
    }

    public FundamentalTrader(String traderId, DeterministicRandom rng, double fundamentalValue, double kappa1, double kappa2, int numTraders, int updateInterval) {
        super(traderId, rng);
        this.fundamentalValue = fundamentalValue;
        this.kappa1 = kappa1;
        this.kappa2 = kappa2;
        this.numTraders = numTraders;
        this.updateInterval = updateInterval;
    }

    @Override
    public List<Order> decide(MarketSnapshot snapshot) {
        ArrayList<Order> orders = new ArrayList<Order>();
        double currentPrice = this.getMidPrice(snapshot, this.fundamentalValue);
        double mispricing = this.fundamentalValue - currentPrice;
        double absMispricing = Math.abs(mispricing);
        double demand = this.kappa1 * absMispricing + this.kappa2 * Math.pow(absMispricing, 3.0);
        double mu = demand / (double)this.numTraders;
        mu /= 100.0;
        mu = Math.min(mu, 1.0);
        int step = snapshot.getStep();
        if (step % this.updateInterval == 0 && this.rng.nextDouble() < mu) {
            if (mispricing > 0.0) {
                orders.add(this.createMarketOrder("BUY", 100));
            } else if (mispricing < 0.0) {
                orders.add(this.createMarketOrder("SELL", 100));
            }
        }
        return orders;
    }

    public void setFundamentalValue(double value) {
        this.fundamentalValue = value;
    }
}
