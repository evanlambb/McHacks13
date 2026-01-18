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

public class MomentumTrader
extends BaseTrader {
    private double rho;
    private double chi;
    private double psi;
    private double delta;
    private int numTraders;
    private double momentum = 0.0;
    private double lastPrice = 0.0;

    public MomentumTrader(String traderId, DeterministicRandom rng, double alpha, double beta) {
        this(traderId, rng, alpha, beta, beta * 0.3, 0.05, 1);
    }

    public MomentumTrader(String traderId, DeterministicRandom rng, double alpha, double beta, int numTraders) {
        this(traderId, rng, alpha, beta, beta * 0.3, 0.05, numTraders);
    }

    public MomentumTrader(String traderId, DeterministicRandom rng, double rho, double chi, double psi, double delta, int numTraders) {
        super(traderId, rng);
        this.rho = rho;
        this.chi = chi;
        this.psi = psi;
        this.delta = delta;
        this.numTraders = numTraders;
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
        double currentPrice = this.getMidPrice(snapshot, 0.0);
        if (currentPrice == 0.0) {
            return orders;
        }
        if (this.lastPrice > 0.0) {
            double priceChange = currentPrice - this.lastPrice;
            this.momentum = (1.0 - this.rho) * this.momentum + this.rho * priceChange;
        }
        double tanhMomentum = Math.tanh(this.momentum);
        double alpha = Math.abs(this.chi * tanhMomentum / (double)this.numTraders);
        double beta = Math.abs(this.psi * tanhMomentum / (double)this.numTraders);
        alpha = Math.min(alpha, 1.0);
        beta = Math.min(beta, 1.0);
        if (this.rng.nextDouble() < alpha && this.momentum != 0.0) {
            side = this.momentum > 0.0 ? "BUY" : "SELL";
            double priceOffset = this.rng.nextLogNormal(-5.0, 1.0) / 10000.0;
            double limitPrice = currentPrice + (side.equals("BUY") ? -priceOffset : priceOffset);
            limitPrice = (double)Math.round(limitPrice * 10.0) / 10.0;
            orders.add(this.createLimitOrder(side, limitPrice, 100));
        }
        if (this.rng.nextDouble() < beta && this.momentum != 0.0) {
            side = this.momentum > 0.0 ? "BUY" : "SELL";
            orders.add(this.createMarketOrder(side, 100));
        }
        this.lastPrice = currentPrice;
        return orders;
    }
}
