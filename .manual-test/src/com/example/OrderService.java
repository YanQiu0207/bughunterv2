package com.example;

public class OrderService {
    public int total(Order order) {
        return order.getAmount();
    }

    public int handle() {
        Order order = null;
        return total(order);
    }
}

class Order {
    int getAmount() {
        return 1;
    }
}
