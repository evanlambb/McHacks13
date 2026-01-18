/*
 * Decompiled with CFR 0.152.
 */
package ca.mc.exchange_simulator.traders;

import ca.mc.exchange_simulator.core.CancelOrder;
import ca.mc.exchange_simulator.core.DeterministicRandom;
import ca.mc.exchange_simulator.core.Fill;
import ca.mc.exchange_simulator.core.MarketSnapshot;
import ca.mc.exchange_simulator.core.Order;
import java.util.ArrayList;
import java.util.List;

public abstract class BaseTrader {
    protected String traderId;
    protected DeterministicRandom rng;
    protected int position = 0;
    protected double limitOrderProbability = 0.0;
    protected double marketOrderProbability = 0.0;
    protected double cancelOrderProbability = 0.0;
    protected final int qty = 100;
    protected double marketLimitRatio = 0.0;
    protected List<String> activeOrderIds = new ArrayList<String>();

    public BaseTrader(String traderId, DeterministicRandom rng) {
        this.traderId = traderId;
        this.rng = rng;
    }

    public abstract List<Order> decide(MarketSnapshot var1);

    public void onFill(Fill fill) {
        this.position = fill.getSide().equals("BUY") ? (this.position += fill.getQty()) : (this.position -= fill.getQty());
        if (fill.getRemainingQty() <= 0) {
            this.activeOrderIds.remove(fill.getOrderId());
        }
    }

    public String getTraderId() {
        return this.traderId;
    }

    protected Order createMarketOrder(String side, int qty) {
        double price = side.equals("BUY") ? 1000000.0 : 0.01;
        Order order = new Order(this.traderId, this.generateOrderId(), side, price, qty);
        order.setMarketOrder(true);
        order.setSelfTradeAllowed(true);
        return order;
    }

    protected Order createLimitOrder(String side, double price, int qty) {
        Order order = new Order(this.traderId, this.generateOrderId(), side, price, qty);
        order.setSelfTradeAllowed(true);
        this.activeOrderIds.add(order.getOrderId());
        return order;
    }

    protected CancelOrder createCancelOrder(String targetOrderId) {
        this.activeOrderIds.remove(targetOrderId);
        return new CancelOrder(this.traderId, this.generateOrderId(), targetOrderId);
    }

    private String generateOrderId() {
        return this.traderId + "_" + System.nanoTime() + "_" + this.rng.nextInt(1000);
    }

    protected double getMidPrice(MarketSnapshot snapshot, double fallbackPrice) {
        double bestBid = snapshot.getBid();
        double bestAsk = snapshot.getAsk();
        if (bestBid == 0.0 && bestAsk == 0.0) {
            return fallbackPrice;
        }
        if (bestBid == 0.0) {
            return bestAsk;
        }
        if (bestAsk == 0.0) {
            return bestBid;
        }
        return (bestBid + bestAsk) / 2.0;
    }
}
