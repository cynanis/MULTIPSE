from logging import exception, raiseExceptions
from os import path
import torch 
import numpy as np
from random import randint
import cv2
from torch._C import clear_autocast_cache
from utils.utils_blindsr import degradation_bsrgan, degradation_bsrgan_plus_an
from torchvision import transforms, utils
import re
import collections
from torch._six import string_classes
import random
from utils.mask_utils import get_random_points,get_bezier_curve
from utils import utils_blindsr
np_str_obj_array_pattern = re.compile(r'[SaUO]')


default_collate_err_msg_format = (
    "default_collate: batch must contain tensors, numpy arrays, numbers, "
    "dicts or lists; found {}")


class DataBatch:
    def __init__(self,transfrom,max_box,max_cells,devider=4,force_size = None):
        self.transfrom = transfrom
        self.max_box = max_box
        self.max_cells = max_cells
        self.devider = devider
        self.force_size = force_size
        


    def collate_fn(self,batch):
        
        #calculate img crop size
        min_h,max_h,min_w,max_w = self.max_box
        patch_h = 2000
        patch_w = 2000
        while(patch_h*patch_w > self.max_cells or (patch_h%self.devider !=0 or patch_w%self.devider !=0)):
            patch_h = randint(min_h,max_h) 
            patch_w = patch_h #randint(min_w,max_w)

        if(self.force_size is not None):
            patch_h = self.force_size
            patch_w = self.force_size

        crop = FaceCrop()
        rescale = FaceRescale((patch_h,patch_w),(patch_h,patch_w))
        smooth = FaceSmooth()

        batch_= []
        for sample in batch:
            sample_ = crop(sample)
            sample_ = rescale(sample_)
            sample_ = smooth(sample_)
            sample_ = self.transfrom(sample_)
            # print(sample_["img_H"].size())
            # print(sample_["img_L"].size())

            batch_.append(sample_)

        # elem = batch[0]
        # return {key: self.cellect([d[key] for d in batch]) for key in elem}
        return self.default_collate(batch_)

    # def cellect(self,batch):
    #     elem = batch[0]
    #     elem_type = type(elem)
    #     out = None
    #     if torch.utils.data.get_worker_info() is not None:
    #         # If we're in a background process, concatenate directly into a
    #         # shared memory tensor to avoid an extra copy
    #         numel = sum(x.numel() for x in batch)
    #         storage = elem.storage()._new_shared(numel)
    #         out = elem.new(storage)
    #     return torch.stack(batch, 0, out=out)


    def default_collate(self,batch):
        r"""Puts each data field into a tensor with outer dimension batch size"""

        elem = batch[0]
        elem_type = type(elem)
        if isinstance(elem, torch.Tensor):
            out = None
            if torch.utils.data.get_worker_info() is not None:
                # If we're in a background process, concatenate directly into a
                # shared memory tensor to avoid an extra copy
                numel = sum(x.numel() for x in batch)
                storage = elem.storage()._new_shared(numel)
                out = elem.new(storage)
            return torch.stack(batch, 0, out=out)
        elif elem_type.__module__ == 'numpy' and elem_type.__name__ != 'str_' \
                and elem_type.__name__ != 'string_':
            if elem_type.__name__ == 'ndarray' or elem_type.__name__ == 'memmap':
                # array of string classes and object
                if np_str_obj_array_pattern.search(elem.dtype.str) is not None:
                    raise TypeError(default_collate_err_msg_format.format(elem.dtype))

                return self.default_collate([torch.as_tensor(b) for b in batch])
            elif elem.shape == ():  # scalars
                return torch.as_tensor(batch)
        elif isinstance(elem, float):
            return torch.tensor(batch, dtype=torch.float64)
        elif isinstance(elem, int):
            return torch.tensor(batch)
        elif isinstance(elem, string_classes):
            return batch
        elif isinstance(elem, collections.abc.Mapping):
            try:
                return elem_type({key: self.default_collate([d[key] for d in batch]) for key in elem})
            except TypeError:
                # The mapping type may not support `__init__(iterable)`.
                return {key: self.default_collate([d[key] for d in batch]) for key in elem}
        elif isinstance(elem, tuple) and hasattr(elem, '_fields'):  # namedtuple
            return elem_type(*(self.default_collate(samples) for samples in zip(*batch)))
        elif isinstance(elem, collections.abc.Sequence):
            # check to make sure that the elements in batch have consistent size
            it = iter(batch)
            elem_size = len(next(it))
            if not all(len(elem) == elem_size for elem in it):
                raise RuntimeError('each element in list of batch should be of equal size')
            transposed = list(zip(*batch))  # It may be accessed twice, so we use a list.

            if isinstance(elem, tuple):
                return [self.default_collate(samples) for samples in transposed]  # Backwards compatibility.
            else:
                try:
                    return elem_type([self.default_collate(samples) for samples in transposed])
                except TypeError:
                    # The sequence type may not support `__init__(iterable)` (e.g., `range`).
                    return [self.default_collate(samples) for samples in transposed]

        raise TypeError(default_collate_err_msg_format.format(elem_type))









class FaceCrop(object):

    def __call__(self, sample):

        img_H= sample['img_H']

        h, w = img_H.shape[:2]
        if(h == w):
            return sample
        elif(h > w):
            lq_patchsize = w -1
        else:
            lq_patchsize = h -1

        rnd_h = random.randint(0, h-lq_patchsize)
        rnd_w = random.randint(0, w-lq_patchsize)

        rnd_h_H, rnd_w_H = int(rnd_h), int(rnd_w)
        img_H_ = img_H.copy()[rnd_h_H:rnd_h_H + lq_patchsize, rnd_w_H:rnd_w_H + lq_patchsize, :]
        # print("img_H_",img_H_.shape)
        return {'img_H': img_H_}   








class FaceRescale(object):
    """Rescale the image in a sample to a given size.

    Args:
        output_size (tuple or int): Desired output size. If tuple, output is
            matched to output_size. If int, smaller of image edges is matched
            to output_size keeping aspect ratio the same.
    """

    def __init__(self ,input_size,output_size):
        assert isinstance(output_size, (int, tuple))
        self.output_size = output_size
        self.input_size = input_size
  

    def __call__(self, sample):

        img_H= sample['img_H']

        h, w = img_H.shape[:2]
        if(h == self.input_size and w == self.input_size):
            return {'img_H': img_H, 'img_L': img_H}  

        if isinstance(self.input_size, int):
            if h > w:
                new_h, new_w = self.input_size * h / w, self.input_size
            else:
                new_h, new_w = self.input_size, self.input_size * w / h
        else:
            new_h, new_w = self.input_size

        new_h, new_w = int(new_h), int(new_w)
        
        img_L_ = cv2.resize(img_H, (new_h, new_w), interpolation=cv2.INTER_CUBIC)
        # print("img_L",img_L_.shape)

        if isinstance(self.output_size, int):
            if h > w:
                new_h, new_w = self.output_size * h / w, self.output_size
            else:
                new_h, new_w = self.output_size, self.output_size * w / h
        else:
            new_h, new_w = self.output_size

        new_h, new_w = int(new_h), int(new_w)
        interpolate= random.choice([1, 2, 3]);

        img_H_ = cv2.resize(img_H, (new_h, new_w), interpolation=interpolate)
        # print("img_H_",img_H_.shape)



    

        return {'img_H': img_H_, 'img_L': img_L_}     




class FaceSmooth(object):
 

    def __call__(self, sample):

        img_H, img_L= sample['img_H'], sample['img_L']
        r = randint(1,16)
        if(r == 3 or r == 6):
            i = randint(2,5)
            img_H_ = cv2.blur(img_H,(i,i))
            img_L_ = cv2.blur(img_L,(i,i))
        else:
            img_H_ = img_H
            img_L_ = img_L

        return {'img_H': img_H_, 'img_L': img_L_}   










class AddMaskFace(object):
    """Convert ndarrays in sample to Tensors."""
    def __init__(self,color = (0,0,0)):
        self.output_size = None
        self.masks = [self.circle,self.arbitrary_shape,self.line,self.circle,self.arbitrary_shape,self.rectangle,self.circle_mask]
        self.color = color

    def __call__(self, sample):
        img_H,img_L = sample['img_H'] , sample["img_L"]

        img_H = cv2.cvtColor(img_H, cv2.COLOR_BGR2RGB)
        img_L = cv2.cvtColor(img_L, cv2.COLOR_BGR2RGB)
        h, w = img_L.shape[:2]
        self.output_size = min(h,w)
        # img_L = self.masks[6](img_L)
        for i in range(randint(2,5)):
            img_L = self.masks[randint(0,4)](img_L)

        # print("img_L",img_L.shape)

        return {'img_H': img_H,'img_L': img_L}

    def line(self,image):
        offset = int(self.output_size / 9)
        threshold = int(self.output_size / 5)
        line_dim = 50000;
        while(line_dim > threshold):
            s_h = randint(offset,self.output_size-offset)
            s_w = randint(offset,self.output_size-offset)
            e_h = randint(s_h,self.output_size-offset)
            e_w = randint(s_w,self.output_size-offset)
            line_dim = np.sqrt((s_h - e_h)**2 + (s_w - e_w)**2)

        img_masked = cv2.line(
            image,
            pt1 = (s_w, s_h), pt2 = (e_w, e_h),
            color = self.color,
            thickness = randint(int(self.output_size/50),int(self.output_size/20)))
        return img_masked    
    
    def rectangle(self,image):
        offset = int(self.output_size / 9)
        threshold = int(self.output_size / 5)
        line_dim = 50000;
        while(line_dim > threshold):
            s_h = randint(offset,self.output_size-offset)
            s_w = randint(offset,self.output_size-offset)
            e_h = randint(s_h,self.output_size-offset)
            e_w = randint(s_w,self.output_size-offset)
            line_dim = np.sqrt((s_h - e_h)**2 + (s_w - e_w)**2)

        
        img_masked = cv2.rectangle(
                image,
                pt1 = (s_w, s_h), pt2 = (e_w, e_h),
                color = self.color,
                thickness = -1)
        return img_masked 

    def circle(self,image):
        s_h = randint(int(self.output_size/2-(self.output_size/3)),self.output_size-10)
        s_w = randint(int(self.output_size/2-(self.output_size/3)),self.output_size-10)
        raduis = randint(int(self.output_size/70),int(min(self.output_size - max(s_h,s_w),int(self.output_size/16))))
        
        img_masked = cv2.circle(
                    image,
                    center = (s_w, s_h),
                    radius = raduis,
                    color = self.color,
                    thickness = -1
                    )
        return img_masked

    def circle_mask(self,image):
        s_h = randint(int(self.output_size/2-(self.output_size/3)),self.output_size-10)
        s_w = randint(int(self.output_size/2-(self.output_size/3)),self.output_size-10)
        raduis = randint(5,int(min(self.output_size - max(s_h,s_w),int(self.output_size/18))))
        
        img_masked = cv2.circle(
                    image,
                    center = (s_w, s_h),
                    radius = raduis,
                    color = self.color,
                    thickness = randint(1,4)
                    )
        return img_masked


    def arbitrary_shape(self,image):
        offset = int(self.output_size / 7)
        rad = 0.2
        edgy = 0.05
        c = [randint(offset,self.output_size-offset),randint(offset,self.output_size-offset)]
        a = get_random_points(n=randint(5,20), scale=randint(2,int(self.output_size/7))) + c
        x,y, _ = get_bezier_curve(a,rad=rad, edgy=edgy)
        pts = np.array([x[:],y[:]]).T
        pts = pts.reshape((-1,1,2)).astype(np.int32)
        masked_image = cv2.polylines(image,[pts],True,color = self.color,thickness=randint(int(self.output_size/50),int(self.output_size/20)))
        return masked_image


class FaceNormalize(object):
    """Convert ndarrays in sample to Tensors."""

    def __call__(self, sample):

        img_H,img_L = sample['img_H'] , sample["img_L"]

        img_H = np.float32(img_H/255.)
        img_L = np.float32(img_L/255.)

        sample_ ={'img_H': img_H, 'img_L': img_L}               
  
        return sample_


class FaceToTensor(object):
    """Convert ndarrays in sample to Tensors."""

    def __call__(self, sample):
        img_H,img_L = sample['img_H'] , sample["img_L"]

        #convert to tensor
        img_H = torch.from_numpy(img_H)
        img_L = torch.from_numpy(img_L)
        # torch image: C x H x W
        img_L = img_L.permute(2, 0, 1).float()
        img_H = img_H.permute(2, 0, 1).float()
        # print("img_L",img_L.shape)
        # print("img_H",img_H.shape)

        return {'img_H': img_H,'img_L': img_L}        
