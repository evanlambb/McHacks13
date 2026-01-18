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

public class NoiseTrader
extends BaseTrader {
    private double eta;
    private double kappa;
    private double delta;
    private int numTraders;
    private double fundamentalValue;
    private double alpha;
    private double beta;

    public NoiseTrader(String traderId, DeterministicRandom rng, double sigma) {
        this(traderId, rng, sigma, 0.25, 0.1, 1, 4500.0);
    }

    public NoiseTrader(String traderId, DeterministicRandom rng, double sigma, int numTraders) {
        this(traderId, rng, sigma, 0.25, 0.1, numTraders, 4500.0);
    }

    public NoiseTrader(String traderId, DeterministicRandom rng, double sigma, double fundamentalValue) {
        this(traderId, rng, sigma, 0.25, 0.1, 1, fundamentalValue);
    }

    public NoiseTrader(String traderId, DeterministicRandom rng, double sigma, int numTraders, double fundamentalValue) {
        this(traderId, rng, sigma, 0.25, 0.1, numTraders, fundamentalValue);
    }

    public NoiseTrader(String traderId, DeterministicRandom rng, double eta, double kappa, double delta, int numTraders, double fundamentalValue) {
        super(traderId, rng);
        this.eta = eta;
        this.kappa = kappa;
        this.delta = delta;
        this.numTraders = numTraders;
        this.fundamentalValue = fundamentalValue;
        this.alpha = Math.min(Math.abs(eta) / (double)numTraders, 1.0);
        this.beta = kappa * this.alpha;
    }

    @Override
    public List<Order> decide(MarketSnapshot snapshot) {
        String side;
        ArrayList<Order> orders = new ArrayList<Order>();
        ArrayList<String> toCancel = new ArrayList<String>();
        for (String orderId : this.activeOrderIds) {
            if (!(this.rng.nextDouble() < this.delta)) continue;
            toCancel.add(orderId);
        }
        for (String orderId : toCancel) {
            orders.add(this.createCancelOrder(orderId));
        }
        double currentPrice = this.getMidPrice(snapshot, this.fundamentalValue);
        if (this.rng.nextDouble() < this.alpha) {
            side = this.rng.nextDouble() < 0.5 ? "BUY" : "SELL";
            double priceOffset = this.rng.nextLogNormal(-5.0, 1.0) / 10000.0;
            double limitPrice = currentPrice + (side.equals("BUY") ? -priceOffset : priceOffset);
            limitPrice = (double)Math.round(limitPrice * 10.0) / 10.0;
            orders.add(this.createLimitOrder(side, limitPrice, 100));
        }
        if (this.rng.nextDouble() < this.beta) {
            side = this.rng.nextDouble() < 0.5 ? "BUY" : "SELL";
            orders.add(this.createMarketOrder(side, 100));
        }
        return orders;
    }
}
