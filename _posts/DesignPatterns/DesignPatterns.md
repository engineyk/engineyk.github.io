[设计模式](https://refactoringguru.cn/design-patterns/catalog)
# 创建型模式
- 简单工厂模式
- 工厂方法模式
- 抽象工厂模式
- 生成器模式
- 原型模式
- 单例模式

# 结构型设计模式

- 适配器模式
- 桥接模式
- 组合模式
- 装饰模式
- 外观模式
- 享元模式

# 行为型设计模式
- 命令模式
- 迭代器模式
- 中介者模式
- 观察者模式
- 策略模式
- 状态模式
- 模板方法模式


# Factory Method
```c++
public class FoodFactory 
{
    public static Food makeFood(String name)
    {
        if (name.equals("noodle")) {
            Food noodle = new LanZhouNoodle();
            noodle.addSpicy("more");
            return noodle;
        } else if (name.equals("chicken")) {
            Food chicken = new HuangMenChicken();
            chicken.addCondiment("potato");
            return chicken;
        } else {
            return null;
        }
    }
}
```

# 生成器模式
build­Walls创建墙壁
build­Door创建房门

# Abstract Factory
抽象工厂模式

```c++
public interface FoodFactory {
    Food makeFood(String name);
}
public class ChineseFoodFactory implements FoodFactory {
    public Food makeFood(String name) {
     }
}
public class AmericanFoodFactory implements FoodFactory {
    public Food makeFood(String name) {
     }
}
public class APP {
    public static void main(String[] args) {
        // 先选择一个具体的工厂
        FoodFactory factory = new ChineseFoodFactory();
        // 由第一步的工厂产生具体的对象，不同的工厂造出不一样的对象
        Food food = factory.makeFood("A");
    }
}
var fac = 地下城工厂 or 道馆工厂
fac .CreateFightFSM()

产品族：兼容问题，多个工厂生产的CPU和主板不兼容
public static void main(String[] args)
 {
    // 第一步就要选定一个“大厂”
    ComputerFactory cf = new AmdFactory();
    // 从这个大厂造 CPU
    CPU cpu = cf.makeCPU();
    // 从这个大厂造主板
    MainBoard board = cf.makeMainBoard();
    // 从这个大厂造硬盘
    HardDisk hardDisk = cf.makeHardDisk();
    // 将同一个厂子出来的 CPU、主板、硬盘组装在一起
    Computer result = new Computer(cpu, board, hardDisk);
}

```

# Builder

```c++
Food food = new FoodBuilder().a().b().c().build();
public static void main(String[] args) {
        User d = User.builder().name("foo") .password("pAss12345").age(25).build();
}
```

# Prototype
（原型）
clone() 

# Singleton
（单例）
```c++
public class Singleton3 {
private Singleton3() {}
    // 主要是使用了 嵌套类可以访问外部类的静态属性和静态方法 的特性
    private static class Holder {
        private static Singleton3 instance = new Singleton3();
    }
    public static Singleton3 getInstance() {
        return Holder.instance;
    }
}

```


# Adapter Class/Object （适配器）
适配器做的是适配的活，为的是提供“把鸡包装成鸭，然后当做鸭来使用”，而鸡和鸭它们之间原本没有继承关系。

## 类适配器
采用继承,属于静态实现
```c++
public class FileAlterationListenerAdaptor implements FileAlterationListener
{
…实现所有接口
}
public class FileMonitor extends FileAlterationListenerAdaptor {
…只实现需要的接口
    public void onFileCreate(final File file) {
        // 文件创建
        doSomething();
    }
public void onFileDelete(final File file) {
        // 文件删除
        doSomething();
    }
}
```

## 对象适配器
野鸡wildCock 使用CockAdapter适配成鸭
采用组合的动态实现
```c++
public static void main(String[] args) {
    // 有一只野鸡
    Cock wildCock = new WildCock();
    // 成功将野鸡适配成鸭
    Duck duck = new CockAdapter(wildCock);
    ...
}
// 毫无疑问，首先，这个适配器肯定需要 implements Duck，这样才能当做鸭来用
public class CockAdapter implements Duck {
    Cock cock;
    // 构造方法中需要一个鸡的实例，此类就是将这只鸡适配成鸭来用
      public CockAdapter(Cock cock) {
        this.cock = cock;
    }
    // 实现鸭的呱呱叫方法
      public void quack() {
        // 内部其实是一只鸡的咕咕叫
        cock.gobble();
    }
    @Override
      public void fly() {
        cock.fly();
    }
}
```

# Bridge 桥接模式
将类拆分为两个类层次结构
- 抽象部分： 程序的 GUI 层
- 实现部分： 操作系统的 API
```
代码抽象和解耦
public static void main(String[] args) {
    Shape greenCircle = new Circle(10, new GreenPen());
    Shape redRectangle = new Rectangle(4, 8, new RedPen());
    greenCircle.draw();
    redRectangle.draw();
}
```

# Composite（组合）

```c++
public class Employee {
   private String name;
   private String dept;
   private int salary;
   private List<Employee> subordinates;
}
```

# Decorator（装饰）
装饰，那么往往就是添加小功能这种
将对象放入包含行为的特殊封装对象中来为原对象绑定新的行为。
```c++
stack = new Notifier()
if (weChatEnabled) {
    stack = new WeChatDecorator(stack)
}
if (qqEnabled) {
    stack=newQQDecorator(stack)
}
app.setNotifier(stack)
```

# Proxy（代理）
对客户端隐藏真实实现
“方法包装” 或做 “方法增强”
```c++
 // 代理要表现得“就像是”真实实现类，所以需要实现 FoodService
public class FoodServiceProxy implements FoodService {
  // 内部一定要有一个真实的实现类，当然也可以通过构造方法注入
  private FoodService foodService = new FoodServiceImpl();
  public Food makeChicken() {
       System.out.println("我们马上要开始制作鸡肉了");
       // 如果我们定义这句为核心代码的话，那么，核心代码是真实实现类做的，
        // 代理只是在核心代码前后做些“无足轻重”的事情
        Food food = foodService.makeChicken();
       System.out.println("鸡肉制作完成啦，加点胡椒粉"); // 增强
       food.addCondiment("pepper");
       return food;
    }
}
```

# Chain of Responsibility
（责任链）

```c++
h1 = new HandlerA()
h2 = new HandlerB()
h3 = new HandlerC()
h1.setNext(h2)
h2.setNext(h3)
// ...
h1.handle(request)

public static void main(String[] args) {
    RuleHandler newUserHandler = new NewUserRuleHandler();
    RuleHandler locationHandler = new LocationRuleHandler();
    RuleHandler limitHandler = new LimitRuleHandler();
    // 假设本次活动仅校验地区和奖品数量，不校验新老用户
    locationHandler.setSuccessor(limitHandler);
    locationHandler.apply(context);
}
public abstract class RuleHandler {
    // 后继节点
    protected RuleHandler successor;
    public abstract void apply(Context context);
    public void setSuccessor(RuleHandler successor) {
        this.successor = successor;
    }
    public RuleHandler getSuccessor() {
        return successor;
    }
}
```

# Strategy（策略）
```c++
str = new SomeStrategy()
context.setStrategy(str)
context.doSomething()
// ...
other = new OtherStrategy()
context.setStrategy(other)
context.doSomething()
```

```c++
public static void main(String[] args) {
    Context context = new Context(new BluePen()); // 使用绿色笔来画
      context.executeDraw(10, 0, 0);
}
public class Context {
   private Strategy strategy;
public Context(Strategy strategy){
      this.strategy = strategy;
   }
public int executeDraw(int radius, int x, int y){
      return strategy.draw(radius, x, y);
   }
}
```

# Visitor（访问者）
```c++
// 客户端代码
foreach (Node node in graph)
    node.accept(exportVisitor)

// 城市
class City is
    method accept(Visitor v) is
        v.doForCity(this)
    // ……

// 工业区
class Industry is
    method accept(Visitor v) is
        v.doForIndustry(this)
    // ……
```