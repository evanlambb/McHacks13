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

public class SpikingTrader
extends BaseTrader {
    private int spikeLength;
    private double activationProbability;
    private int orderVolume;
    private int status = 0;
    private String direction = "SELL";

    public SpikingTrader(String traderId, DeterministicRandom rng, int spikeLength, double activationProbability, int orderVolume) {
        super(traderId, rng);
        this.spikeLength = spikeLength;
        this.activationProbability = activationProbability;
        this.orderVolume = orderVolume;
    }

    @Override
    public List<Order> decide(MarketSnapshot snapshot) {
        ArrayList<Order> orders = new ArrayList<Order>();
        if (this.status > 0) {
            orders.add(this.createMarketOrder(this.direction, this.orderVolume));
            --this.status;
        } else if (this.rng.nextDouble() < this.activationProbability) {
            this.direction = this.rng.nextDouble() < 0.5 ? "SELL" : "BUY";
            this.status = this.spikeLength;
            orders.add(this.createMarketOrder(this.direction, this.orderVolume));
            --this.status;
        }
        return orders;
    }

    public int getStatus() {
        return this.status;
    }

    public String getDirection() {
        return this.direction;
    }

    public double getActivationProbability() {
        return this.activationProbability;
    }

    public void setActivationProbability(double activationProbability) {
        this.activationProbability = activationProbability;
    }
}
