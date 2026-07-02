"""
Async/Await Pattern Optimization
Week 11: Performance Optimization

Optimizations:
- Parallel task execution
- Semaphore-based concurrency control
- Task batching
- Non-blocking operations
"""

import asyncio
import logging
from typing import List, Callable, Any, Optional, Dict
from collections import deque

logger = logging.getLogger(__name__)


class AsyncTaskExecutor:
    """
    Optimized async task executor with concurrency control
    """
    
    def __init__(self, max_concurrent: int = 10):
        """
        Initialize task executor
        
        Args:
            max_concurrent: Maximum concurrent tasks
        """
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.active_tasks = 0
        self.completed_tasks = 0
        self.failed_tasks = 0
    
    async def execute(self, coro: Callable, *args, **kwargs):
        """
        Execute coroutine with concurrency limit
        
        Args:
            coro: Coroutine function
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Coroutine result
        """
        async with self.semaphore:
            self.active_tasks += 1
            try:
                result = await coro(*args, **kwargs)
                self.completed_tasks += 1
                return result
            except Exception as e:
                self.failed_tasks += 1
                logger.error(f"Task execution failed: {e}")
                raise
            finally:
                self.active_tasks -= 1
    
    async def execute_batch(
        self,
        tasks: List[Callable],
        max_concurrent: Optional[int] = None
    ) -> List[Any]:
        """
        Execute batch of tasks in parallel
        
        Args:
            tasks: List of coroutine functions
            max_concurrent: Override max concurrent (optional)
            
        Returns:
            List of results
        """
        if max_concurrent:
            semaphore = asyncio.Semaphore(max_concurrent)
        else:
            semaphore = self.semaphore
        
        async def execute_with_semaphore(coro):
            async with semaphore:
                return await coro()
        
        # Create tasks
        task_objects = [asyncio.create_task(execute_with_semaphore(task)) for task in tasks]
        
        # Wait for all to complete
        results = await asyncio.gather(*task_objects, return_exceptions=True)
        
        # Filter out exceptions
        successful = [r for r in results if not isinstance(r, Exception)]
        failed = [r for r in results if isinstance(r, Exception)]
        
        if failed:
            logger.warning(f"{len(failed)} tasks failed out of {len(tasks)}")
        
        return successful
    
    def get_stats(self) -> dict:
        """Get executor statistics"""
        return {
            'max_concurrent': self.max_concurrent,
            'active_tasks': self.active_tasks,
            'completed_tasks': self.completed_tasks,
            'failed_tasks': self.failed_tasks
        }


class TaskBatcher:
    """
    Batch tasks for efficient processing
    """
    
    def __init__(self, batch_size: int = 10, batch_timeout: float = 0.1):
        """
        Initialize task batcher
        
        Args:
            batch_size: Maximum batch size
            batch_timeout: Maximum time to wait for batch (seconds)
        """
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.batch_queue: deque = deque()
        self.batch_lock = asyncio.Lock()
    
    async def add_task(self, task: Callable, *args, **kwargs):
        """
        Add task to batch
        
        Args:
            task: Coroutine function
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Task result
        """
        async with self.batch_lock:
            # Create task coroutine
            task_coro = task(*args, **kwargs)
            
            # Add to batch
            future = asyncio.Future()
            self.batch_queue.append((task_coro, future))
            
            # Check if batch is ready
            if len(self.batch_queue) >= self.batch_size:
                await self._process_batch()
        
        # Wait for result
        return await future
    
    async def _process_batch(self):
        """Process current batch"""
        if not self.batch_queue:
            return
        
        # Extract batch
        batch = []
        futures = []
        while self.batch_queue and len(batch) < self.batch_size:
            task_coro, future = self.batch_queue.popleft()
            batch.append(task_coro)
            futures.append(future)
        
        # Execute batch in parallel
        results = await asyncio.gather(*batch, return_exceptions=True)
        
        # Set futures
        for future, result in zip(futures, results):
            if not future.done():
                if isinstance(result, Exception):
                    future.set_exception(result)
                else:
                    future.set_result(result)
    
    async def flush(self):
        """Flush remaining tasks"""
        async with self.batch_lock:
            if self.batch_queue:
                await self._process_batch()


class NonBlockingExecutor:
    """
    Execute blocking operations in thread pool without blocking event loop
    """
    
    def __init__(self, max_workers: int = 4):
        """
        Initialize non-blocking executor
        
        Args:
            max_workers: Maximum thread pool workers
        """
        self.max_workers = max_workers
        self.executor = None
        self._loop = None
    
    def _get_executor(self):
        """Get or create executor"""
        if self.executor is None:
            import concurrent.futures
            self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers)
        return self.executor
    
    async def run(self, func: Callable, *args, **kwargs):
        """
        Run blocking function in thread pool
        
        Args:
            func: Blocking function
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Function result
        """
        if self._loop is None:
            self._loop = asyncio.get_event_loop()
        
        executor = self._get_executor()
        return await self._loop.run_in_executor(executor, lambda: func(*args, **kwargs))
    
    def shutdown(self):
        """Shutdown executor"""
        if self.executor:
            self.executor.shutdown(wait=False)


def optimize_async_patterns():
    """
    Utility function to optimize common async patterns
    
    Returns:
        Dictionary of optimized utilities
    """
    return {
        'task_executor': AsyncTaskExecutor(max_concurrent=10),
        'task_batcher': TaskBatcher(batch_size=10, batch_timeout=0.1),
        'non_blocking_executor': NonBlockingExecutor(max_workers=4)
    }

