"""async_await测试用例 - 验证async def与await依赖追踪"""
import asyncio

async def async_helper():
    await asyncio.sleep(0)
    return 1

async def async_processor():
    value = await async_helper()
    return value + 1

async def main():
    result = await async_processor()
    return result + 1

if __name__ == "__main__":
    result = asyncio.run(main())
    print(result)